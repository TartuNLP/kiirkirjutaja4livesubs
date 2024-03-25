# This script is for testing incoming audio stream attributes
import wave

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()


@app.websocket("/")
async def websocket_recording_stream(websocket: WebSocket):
    await websocket.accept()
    frames = []
    try:
        while True:
            recv = await websocket.receive()
            if 'bytes' in recv.keys():
                frames.append(recv['bytes'])
            elif recv['type'] == 'websocket.disconnect':
                raise WebSocketDisconnect

    except WebSocketDisconnect:
        if frames:
            with wave.open("main3_test6.wav", "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)  # 2 bytes == 16 bits
                # wav_file.setframerate(16000)
                wav_file.setframerate(16000)
                print(b''.join(frames))
                wav_file.writeframes(b''.join(frames))

