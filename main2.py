import logging
import sys

message_format = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(format=message_format, stream=sys.stderr, level=logging.INFO)

import ray
import sherpa_onnx

# Needed for loading the speaker change detection model
from pytorch_lightning.utilities import argparse_utils

setattr(argparse_utils, "_gpus_arg_default", lambda x: 0)

from kiirkirjutaja.asr import TurnDecoder
from kiirkirjutaja.lid import LanguageFilter
from kiirkirjutaja.vad2 import SpeechSegmentGenerator
from kiirkirjutaja.turn2 import TurnGenerator
from kiirkirjutaja.presenters2 import WordByWordPresenter
from OnlineSpeakerChangeDetector.online_scd.model import SCDModel

import gc

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from threading import Thread
from contextlib import asynccontextmanager
from kiirkirjutaja.bytestream import Stream


ray.init(num_cpus=4)

models = {}


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


@app.websocket("/")
async def main2(websocket: WebSocket):
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
            if not finishing_up:
                if output_stream.buffer.strip() != '':
                    await websocket.send_json(output_stream.read())

                recv = await websocket.receive()
                # print("Received: \n", recv)
                if recv['type'] == 'websocket.disconnect':
                    raise WebSocketDisconnect
                elif 'bytes' in recv.keys():
                    input_stream.write(recv['bytes'])
                elif 'text' in recv.keys() and recv['text'] == 'Done':
                    speech_segment_generator.flag.set()
                    speech_segment_generator.thread.join()
                    transcription_thread.join()
            elif output_stream.buffer:
                await websocket.send_json(output_stream.read())
            else:
                await websocket.close()
                break
    except WebSocketDisconnect:
        speech_segment_generator.flag.set()
        speech_segment_generator.thread.join()
        transcription_thread.join()
