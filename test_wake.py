import pyaudio
import wave
import requests
import json
import struct
import math
import time

# 리턴제로 설정
CLIENT_ID = "LAYWmCf20LcdLOBsE7l0"
CLIENT_SECRET = "R-nEwLvKaRDuQgj7kgU6whFyrmVWA5kIR8vr6tWf"

CHUNK = 4096
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
SILENCE_THRESHOLD = 100
SILENCE_DURATION = 1.5

def get_access_token():
    url = "https://openapi.vito.ai/v1/authenticate"
    data = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    response = requests.post(url, data=data)
    return response.json()["access_token"]

def get_rms(data):
    count = len(data) // 2
    shorts = struct.unpack("%dh" % count, data)
    sum_squares = sum(s ** 2 for s in shorts)
    return math.sqrt(sum_squares / count) if count > 0 else 0

def speech_to_text(token):
    url = "https://openapi.vito.ai/v1/transcribe"
    headers = {"Authorization": f"Bearer {token}"}
    with open("test.wav", 'rb') as f:
        files = {"file": f}
        data = {"config": json.dumps({"use_diarization": False})}
        response = requests.post(url, headers=headers, files=files, data=data)
    
    task_id = response.json()["id"]
    result_url = f"https://openapi.vito.ai/v1/transcribe/{task_id}"
    while True:
        result = requests.get(result_url, headers=headers).json()
        if result["status"] == "completed":
            if result["results"]["utterances"]:
                return result["results"]["utterances"][0]["msg"]
            return None
        elif result["status"] == "failed":
            return None
        time.sleep(0.1)

def record():
    print("\n🎤 '주비스'라고 말해보세요...")
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                    input=True, input_device_index=1, frames_per_buffer=CHUNK)
    frames = []
    silent_chunks = 0
    started = False
    
    while True:
        data = stream.read(CHUNK, exception_on_overflow=False)
        rms = get_rms(data)
        
        if rms > SILENCE_THRESHOLD:
            started = True
            frames.append(data)
            silent_chunks = 0
        elif started:
            frames.append(data)
            silent_chunks += 1
            if silent_chunks > int(SILENCE_DURATION * RATE / CHUNK):
                break
    
    stream.stop_stream()
    stream.close()
    p.terminate()
    
    wf = wave.open("test.wav", 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(2)
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()

print("=" * 50)
print("웨이크 워드 테스트 - STT 결과 확인")
print("=" * 50)
print("'주비스'를 5번 말해보고 STT가 어떻게 인식하는지 확인")
print("Ctrl+C로 종료")
print("=" * 50)

token = get_access_token()
print("✅ 인증 완료!\n")

results = []
for i in range(5):
    print(f"\n--- 테스트 {i+1}/5 ---")
    record()
    text = speech_to_text(token)
    print(f"📝 STT 결과: {text}")
    if text:
        results.append(text)

print("\n" + "=" * 50)
print("📊 결과 모음:")
for r in results:
    print(f"  - {r}")
print("=" * 50)
