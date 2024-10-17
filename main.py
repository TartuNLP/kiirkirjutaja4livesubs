import logging
import sys
import time

message_format = "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"
logging.basicConfig(format=message_format, stream=sys.stderr, level=logging.INFO)

import ray
import sherpa_onnx

# Needed for loading the speaker change detection model
from pytorch_lightning.utilities import argparse_utils

setattr(argparse_utils, "_gpus_arg_default", lambda x: 0)

from kiirkirjutaja.asr import TurnDecoder
from kiirkirjutaja.lid import LanguageFilter
from kiirkirjutaja.vad import SpeechSegmentGenerator
from kiirkirjutaja.turn import TurnGenerator
from kiirkirjutaja.presenters import WordByWordPresenter
from OnlineSpeakerChangeDetector.online_scd.model import SCDModel

import gc

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from threading import Thread
from contextlib import asynccontextmanager
from kiirkirjutaja.bytestream import Stream


ray.init(num_cpus=4)

models = {}

probe_variables = {"started": False, "ready": False}


def process_result(result):
    text = ""
    if "result" in result:
        result_words = []
        for word in result["result"]:
            if word["word"] in ",.!?" and len(result_words) > 0:
                result_words[-1]["word"] += word["word"]
            else:
                result_words.append(word)
        result["result"] = result_words
        return result
    else:
        return result


# https://fastapi.tiangolo.com/advanced/events/#lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # This is loaded here to allow a clean exit (see post-yield)
    models["presenter"] = WordByWordPresenter(word_delay_secs=0.0)
    # The rest is loaded here to reduce client spin-up time since the models are already ready-to-go
    models["language_filter"] = LanguageFilter()
    models["scd_model"] = SCDModel.load_from_checkpoint("models/online-speaker-change-detector/checkpoints/epoch=102.ckpt")
    models["sherpa_model"] = sherpa_onnx.OnlineRecognizer(
        tokens="models/sherpa/tokens.txt",
        encoder="models/sherpa/encoder.onnx",
        decoder="models/sherpa/decoder.onnx",
        joiner="models/sherpa/joiner.onnx",
        num_threads=2,
        sample_rate=16000,
        feature_dim=80,
        enable_endpoint_detection=True,
        rule1_min_trailing_silence=5.0,
        rule2_min_trailing_silence=2.0,
        rule3_min_utterance_length=300,
        decoding_method="modified_beam_search",
        max_feature_vectors=1000,  # 10 seconds
    )

    probe_variables["started"] = True

    # This runs the rest of the program, everything after it is called on exit
    yield

    # This is needed for a clean exit
    models["presenter"].event_scheduler.stop()


app = FastAPI(lifespan=lifespan)


def main_loop(speech_segment_generator):

    for speech_segment in speech_segment_generator.speech_segments():
        models["presenter"].segment_start()

        speech_segment_start_time = speech_segment.start_sample / 16000

        turn_generator = TurnGenerator(models["scd_model"], speech_segment)
        for i, turn in enumerate(turn_generator.turns()):
            if i > 0:
                models["presenter"].new_turn()
            turn_start_time = (speech_segment.start_sample + turn.start_sample) / 16000

            turn_decoder = TurnDecoder(models["sherpa_model"], models["language_filter"].filter(turn.chunks()))
            for res in turn_decoder.decode_results():
                if "result" in res:
                    processed_res = process_result(res)
                    if res["final"]:
                        models["presenter"].final_result(processed_res["result"])
                    # TODO: What if we ignore partial results entirely? (do I understand this correctly?)
                    else:
                        models["presenter"].partial_result(processed_res["result"])
        models["presenter"].segment_end()
        gc.collect()
    # print("main_loop exiting...")


# Instead of sending out strings with line breaks in the middle,
# split them to separate substrings without removing the line breaks.
# This simplifies client-side processing.
async def send_from_stream(websocket, stream_output):
    # This will add a line break to the last substring even if it didn't originally have one!
    # for string in [i+"\n" for i in stream_output.split("\n") if i != ""]:
    # Also, it helps to split on full stops
    # (e.g. "sentenceEndingWord. SentenceStartingWord" -> "sentenceEndingWord." & " SentenceStartingWord").
    # Thus, a more complex solution is needed instead:
    substrings = stream_output.replace(". ", ".\n ").split("\n")
    for string in [j for j in [i+"\n" for i in substrings[:-1]] + [substrings[-1]] if j != ""]:
        await websocket.send_json(string)

# Probe endpoints

@app.get("/liveness")
def liveness():
    return status.HTTP_200_OK

@app.get("/readiness")
def readiness():
    if probe_variables["ready"]:
        return status.HTTP_200_OK
    else:
        return status.HTTP_503_SERVICE_UNAVAILABLE

@app.get("/startup")
def startup():
    if probe_variables["started"]:
        return status.HTTP_200_OK
    else:
        return status.HTTP_503_SERVICE_UNAVAILABLE


@app.websocket("/")
async def main(websocket: WebSocket):
    probe_variables["ready"] = False
    models["presenter"].event_scheduler.start()
    input_stream = Stream(b'')

    await websocket.accept()
    output_stream = Stream("")
    models["presenter"].output_stream = output_stream

    # TODO: Test the try-except loop (stop everything) for WebSocketDisconnects (e.g. browser refresh)
    speech_segment_generator = SpeechSegmentGenerator(input_stream)
    transcription_thread = Thread(target=main_loop, args=(speech_segment_generator,))
    transcription_thread.start()

    finishing_up = False
    try:
        while True:
            if output_stream.buffer.strip() != '':
                await send_from_stream(websocket, output_stream.read())
                # await websocket.send_json(output_stream.read())

            if not finishing_up:
                recv = await websocket.receive()
                # print("Received: \n", recv)
                if recv['type'] == 'websocket.disconnect':
                    raise WebSocketDisconnect
                elif 'bytes' in recv.keys():
                    input_stream.write(recv['bytes'])
                elif 'text' in recv.keys() and recv['text'] == 'Done':
                    finishing_up = True
                    speech_segment_generator.flag.set()
                    speech_segment_generator.thread.join()
                    transcription_thread.join()
                    # The presenter cannot be restarted with each connection,
                    # so just wait for it to finish sending data
                    time.sleep(5)
            elif output_stream.buffer:
                await send_from_stream(websocket, output_stream.read())
                # await websocket.send_json(output_stream.read())
            else:
                await websocket.close()
                probe_variables["ready"] = True
                break
    except WebSocketDisconnect:
        speech_segment_generator.flag.set()
        speech_segment_generator.thread.join()
        transcription_thread.join()
        probe_variables["ready"] = True
