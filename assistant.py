import pyaudio
import wave
import requests
import json
import subprocess
import anthropic
import google.generativeai as genai
from google.cloud import texttospeech
import struct
import math
import time
import os
import re
from difflib import SequenceMatcher
import pickle
from supabase import create_client
from mem0 import MemoryClient

# ============ Supabase 설정 ============
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============ Mem0 설정 ============
MEM0_API_KEY = os.getenv("MEM0_API_KEY")
MEM0_USER_ID = "junseok"
mem0_client = MemoryClient(api_key=MEM0_API_KEY)

# 자동 태깅 대기 상태
pending_tag_info = None

# ============ API 설정 ============
CLIENT_ID = os.getenv("RETURNZERO_CLIENT_ID")
CLIENT_SECRET = os.getenv("RETURNZERO_CLIENT_SECRET")
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/home/dhwnstjr0/ai-assistant/google_tts_key.json"
genai.configure(api_key=GEMINI_API_KEY)

# ============ 오디오 설정 ============
CHUNK = 4096
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
WAVE_FILE = "input.wav"
OUTPUT_FILE = "output.mp3"
SILENCE_THRESHOLD = 300
SILENCE_DURATION = 1.5

HISTORY_FILE = "/home/dhwnstjr0/ai-assistant/conversation_history.pkl"
MAX_HISTORY = 100

def load_history():
    try:
        with open(HISTORY_FILE, 'rb') as f:
            return pickle.load(f)
    except:
        return []

def save_history(history):
    with open(HISTORY_FILE, 'wb') as f:
        pickle.dump(history, f)

def load_from_supabase():
    try:
        response = supabase.table("conversations").select("role, content").order("created_at", desc=True).limit(10).execute()
        if response.data:
            conversations = list(reversed(response.data))
            return [{"role": c["role"], "content": c["content"]} for c in conversations]
    except Exception as e:
        print(f"Supabase 불러오기 오류: {e}")
    return []

def save_to_supabase(role, content):
    try:
        supabase.table("conversations").insert({
            "role": role,
            "content": content,
            "source": "raspberry"
        }).execute()
    except Exception as e:
        print(f"Supabase 저장 오류: {e}")

# ============ Mem0 함수들 ============
def add_to_mem0(text):
    try:
        mem0_client.add(text, user_id=MEM0_USER_ID)
        print(f"🧠 Mem0에 저장됨")
    except Exception as e:
        print(f"Mem0 저장 오류: {e}")

def search_mem0(query):
    try:
        results = mem0_client.search(query, user_id=MEM0_USER_ID, filters={"user_id": MEM0_USER_ID})
        if results and results.get("results"):
            memories = [r["memory"] for r in results["results"][:5]]
            return memories
    except Exception as e:
        print(f"Mem0 검색 오류: {e}")
    return []

def get_all_mem0():
    try:
        results = mem0_client.get_all(user_id=MEM0_USER_ID)
        if results and results.get("results"):
            return [r["memory"] for r in results["results"]]
    except Exception as e:
        print(f"Mem0 전체 조회 오류: {e}")
    return []

# 시작 시 Supabase에서 대화 불러오기
print("📡 Supabase에서 대화 기록 불러오는 중...")
conversation_history = load_from_supabase()
if conversation_history:
    print(f"✅ 최근 대화 {len(conversation_history)}개 불러옴")
else:
    conversation_history = load_history()
    print("📂 로컬 백업에서 대화 불러옴")

# ============ Supabase 태그 함수들 ============
def normalize_tag(tag):
    tag = tag.lower().replace(" ", "").replace(".", "")
    replacements = {
        "에이": "a", "비": "b", "씨": "c", "디": "d", "이": "e",
        "에프": "f", "지": "g", "에이치": "h", "아이": "i", "제이": "j",
        "케이": "k", "엘": "l", "엠": "m", "엔": "n", "오": "o",
        "피": "p", "큐": "q", "알": "r", "에스": "s", "티": "t",
        "유": "u", "브이": "v", "더블유": "w", "엑스": "x", "와이": "y", "제트": "z"
    }
    for kor, eng in replacements.items():
        tag = tag.replace(kor, eng)
    return tag

def get_all_tags():
    try:
        response = supabase.table("tags").select("tag_name").execute()
        if response.data:
            return list(set([item["tag_name"] for item in response.data]))
    except Exception as e:
        print(f"태그 목록 조회 오류: {e}")
    return []

def find_similar_tag(tag_name):
    tag_name = normalize_tag(tag_name)
    existing_tags = get_all_tags()
    for existing in existing_tags:
        existing_norm = normalize_tag(existing)
        if tag_name == existing_norm:
            return existing
        ratio = SequenceMatcher(None, tag_name, existing_norm).ratio()
        if ratio > 0.7:
            return existing
    return None

def save_to_tag(tag_name, content):
    similar = find_similar_tag(tag_name)
    if similar:
        tag_name = similar
    try:
        supabase.table("tags").insert({
            "tag_name": tag_name,
            "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        }).execute()
        print(f"✅ '{tag_name}' 태그로 저장됨")
        return tag_name
    except Exception as e:
        print(f"태그 저장 오류: {e}")
        return None

def search_tag(tag_name):
    similar = find_similar_tag(tag_name)
    if not similar:
        return None, []
    try:
        response = supabase.table("tags").select("*").eq("tag_name", similar).order("created_at", desc=True).execute()
        return similar, response.data if response.data else []
    except Exception as e:
        print(f"태그 검색 오류: {e}")
        return similar, []

def get_tag_context(question):
    keywords = {
        "여자친구": ["여자친구", "여친", "애인", "사귀", "연인"],
        "생일": ["생일", "태어난", "몇살", "나이"],
        "키": ["키", "신장", "크기"],
        "이름": ["이름", "뭐라고 불러", "누구"],
        "취미": ["취미", "좋아하", "즐겨"],
        "직업": ["직업", "일", "회사", "학교"],
    }
    related_tags = []
    question_lower = question.lower()
    for tag_name, tag_keywords in keywords.items():
        if any(kw in question_lower for kw in tag_keywords):
            found_tag, data = search_tag(tag_name)
            if data:
                for item in data[-3:]:
                    related_tags.append(f"[{found_tag}] {item.get('content', '')}")
    return related_tags

# ============ 자동 태깅 시스템 ============
def detect_important_info(text):
    patterns = {
        "여자친구": [
            r"여자친구.*이름.*[은는이가]?\s*(\S+)",
            r"여친.*이름.*[은는이가]?\s*(\S+)",
            r"애인.*이름.*[은는이가]?\s*(\S+)",
            r"사귀는.*사람.*(\S+)",
            r"여자친구가?\s+(\S+)[이야라고]",
        ],
        "생일": [
            r"내?\s*생일.*(\d+월\s*\d+일)",
            r"(\d+월\s*\d+일).*생일",
            r"생일이?\s*(\d{1,2}[월/\-]\d{1,2})",
        ],
        "키": [
            r"키가?\s*(\d{2,3})\s*(cm|센티)?",
            r"(\d{2,3})\s*(cm|센티).*키",
            r"내\s*키.*(\d{2,3})",
        ],
        "이름": [
            r"내\s*이름.*[은는이가]?\s*(\S+)",
            r"나.*[은는]\s*(\S+)[이야라고]",
            r"(\S+)[이라고]?\s*불러",
        ],
        "취미": [
            r"취미.*[은는이가]?\s*(\S+)",
            r"(\S+)[을를이가]?\s*좋아해",
            r"(\S+)\s*하는\s*거\s*좋아",
        ],
    }
    for tag_name, regex_list in patterns.items():
        for pattern in regex_list:
            match = re.search(pattern, text)
            if match:
                return {
                    "tag_name": tag_name,
                    "content": text,
                    "extracted": match.group(1) if match.groups() else text
                }
    return None

def process_tag_command(text, recent_conversation):
    text_lower = text.lower().replace(" ", "")
    text_spaced = text.lower()

    if "태그" in text_spaced and ("목록" in text_spaced or "뭐있" in text_lower or "알려" in text_spaced and "있" in text_spaced):
        tags = get_all_tags()
        if tags:
            return f"저장된 태그: {', '.join(tags)}"
        else:
            return "아직 저장된 태그가 없어요."

    search_patterns = ["태그에뭐", "태그내용", "태그검색", "태그에있", "태그알려", "태그에서찾"]
    for pattern in search_patterns:
        if pattern in text_lower:
            for p in ["태그에", "태그내", "태그검", "태그알", "태그에서"]:
                if p in text_lower:
                    words = text_spaced.split()
                    for i, w in enumerate(words):
                        if "태그" in w and i > 0:
                            tag_name = words[i-1]
                            found_tag, data = search_tag(tag_name)
                            if data:
                                summaries = [item.get("content", "")[:50] for item in data[-3:]]
                                return f"'{found_tag}' 태그에 {len(data)}개 저장됨: {'; '.join(summaries)}"
                            elif found_tag:
                                return f"'{found_tag}' 태그는 있지만 내용이 없어요."
                            else:
                                return f"'{tag_name}'과 비슷한 태그를 찾지 못했어요. 저장된 태그: {', '.join(get_all_tags())}"
            break

    save_patterns = [
        ("로태그", "로"),
        ("으로태그", "으로"),
        ("에태그", "에"),
        ("태그에저장", "태그에"),
        ("태그에추가", "태그에"),
        ("태그해", "태그"),
    ]

    for pattern, split_word in save_patterns:
        if pattern in text_lower:
            words = text_spaced.split()
            tag_name = None
            for i, word in enumerate(words):
                if "태그" in word:
                    if i > 0 and ("로" in words[i-1] or "에" in words[i-1]):
                        tag_name = words[i-1].replace("로", "").replace("으로", "").replace("에", "")
                    elif "태그에" in word or "태그로" in word:
                        tag_name = word.replace("태그에", "").replace("태그로", "").replace("태그", "")
                    elif i > 0:
                        tag_name = words[i-1]
                    break
            if tag_name and len(tag_name) >= 1 and tag_name not in ["이거", "이걸", "것", "거", "를", "을"]:
                content = " | ".join([f"{c['role']}: {c['content']}" for c in recent_conversation])
                saved_tag = save_to_tag(tag_name, content)
                if saved_tag:
                    return f"'{saved_tag}' 태그로 저장했어요!"
                else:
                    return "태그 저장에 실패했어요."
            else:
                return "어떤 태그로 저장할까요? 예: '업무로 태그해줘' 또는 '업무 태그에 저장해줘'"

    return None

wake_variants = [
    "오비서", "오 비서", "안녕비서", "안녕 비서", "안뇨비서",
    "안뇨오비서", "오빗어", "오빗서", "어비서", "오비써",
    "오빗", "오비", "어빗서", "어비써", "오삐서", "오삐써",
    "오피서", "오피써", "옵비서", "옵서", "오브서",
    "호비서", "호 비서", "허비서", "헤비서",
    "오비스", "오비즈", "오비수", "오비쑤",
    "비서", "비서야", "야비서",
    "김비서", "김비석", "김지석", "이비서"
]

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

def is_wake_word(text):
    if not text:
        return False
    text_clean = text.lower().replace(" ", "").replace(".", "").replace(",", "")
    wake_variants = [
        "오비서", "오 비서", "안녕비서", "안녕 비서", "안뇨비서",
        "안뇨오비서", "오빗어", "오빗서", "어비서", "오비써"
    ]
    for word in wake_variants:
        word_clean = word.replace(" ", "")
        if word_clean in text_clean:
            print(f"✅ 정확 매칭: {word}")
            return True
    if "비서" in text_clean:
        print(f"✅ '비서' 매칭: {text}")
        return True
    for word in wake_variants:
        word_clean = word.replace(" ", "")
        ratio = SequenceMatcher(None, word_clean, text_clean).ratio()
        if ratio > 0.55:
            print(f"✅ 유사도 매칭: {text_clean} ≈ {word} ({ratio:.0%})")
            return True
    return False

def text_to_speech(text):
    print(f"🔊 응답: {text}")
    try:
        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code="ko-KR",
            name="ko-KR-Wavenet-A",
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        with open(OUTPUT_FILE, "wb") as out:
            out.write(response.audio_content)
        subprocess.run(["ffmpeg", "-y", "-i", OUTPUT_FILE, "output.wav"], 
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["aplay", "-D", "plughw:2,0", "output.wav"])
    except Exception as e:
        print(f"TTS 오류: {e}, espeak로 대체")
        subprocess.run(f'espeak -v ko "{text}" --stdout | aplay -D plughw:2,0', shell=True)

def listen_for_wake_word(token):
    print("\n👂 '오 비서'를 기다리는 중...")
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                    input=True, input_device_index=1, frames_per_buffer=CHUNK)
    frames = []
    recording = False
    silent_chunks = 0
    
    while True:
        data = stream.read(CHUNK, exception_on_overflow=False)
        rms = get_rms(data)
        
        if rms > SILENCE_THRESHOLD:
            if not recording:
                recording = True
                frames = []
            frames.append(data)
            silent_chunks = 0
        elif recording:
            frames.append(data)
            silent_chunks += 1
            if silent_chunks > int(SILENCE_DURATION * RATE / CHUNK):
                stream.stop_stream()
                stream.close()
                p.terminate()
                
                if len(frames) < int(0.5 * RATE / CHUNK):
                    p = pyaudio.PyAudio()
                    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                                    input=True, input_device_index=1, frames_per_buffer=CHUNK)
                    recording = False
                    frames = []
                    continue
                
                wf = wave.open(WAVE_FILE, 'wb')
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(2)
                wf.setframerate(RATE)
                wf.writeframes(b''.join(frames))
                wf.close()
                
                print("녹음 완료, STT 호출 중...")
                text = speech_to_text_stt(token)
                print(f"STT 결과: {text}")
                
                if is_wake_word(text):
                    return True
                else:
                    p = pyaudio.PyAudio()
                    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                                    input=True, input_device_index=1, frames_per_buffer=CHUNK)
                    recording = False
                    frames = []

def record_command():
    print("🎤 말씀하세요...")
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
    
    wf = wave.open(WAVE_FILE, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(2)
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()
    print("✅ 녹음 완료!")

def speech_to_text_stt(token):
    url = "https://openapi.vito.ai/v1/transcribe"
    headers = {"Authorization": f"Bearer {token}"}
    with open(WAVE_FILE, 'rb') as f:
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

def classify_question(question):
    print("🧠 질문 분류 중...")
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=10,
        messages=[{"role": "user", "content": f"질문을 분류해. 실시간 정보(날씨,뉴스,주가,시간,검색)면 gemini, 아니면 claude. 한 단어만 답해.\n\n질문: {question}\n답:"}]
    )
    result = message.content[0].text.strip().lower()
    return "gemini" if "gemini" in result else "claude"

def ask_gemini(question):
    global conversation_history
    print("🌐 Gemini 검색 중...")

    conversation_history.append({"role": "user", "content": question})
    save_to_supabase("user", question)
    add_to_mem0(question)

    model = genai.GenerativeModel('gemini-2.0-flash')
    response = model.generate_content(f"친절한 AI 비서로서 짧게 한국어로 답해. 2-3문장.\n\n질문: {question}")
    result = response.text

    conversation_history.append({"role": "assistant", "content": result})
    save_to_supabase("assistant", result)
    save_history(conversation_history)

    return result

def ask_claude(question):
    global conversation_history
    print("🤖 Claude 생각 중...")

    conversation_history.append({"role": "user", "content": question})
    save_to_supabase("user", question)
    add_to_mem0(question)

    if len(conversation_history) > MAX_HISTORY * 2:
        conversation_history = conversation_history[-MAX_HISTORY * 2:]

    mem0_memories = search_mem0(question)
    tag_context = get_tag_context(question)
    
    system_prompt = "친절한 AI 음성 비서 '오 비서'. 짧고 자연스럽게 한국어로 2-3문장 답변. 이전 대화 맥락을 기억해서 답변."

    if mem0_memories:
        mem0_info = "\n".join([f"- {m}" for m in mem0_memories])
        system_prompt += f"\n\n[사용자에 대해 기억하는 정보]\n{mem0_info}"
        print(f"🧠 Mem0 기억 {len(mem0_memories)}개 참조")

    if tag_context:
        tag_info = "\n".join(tag_context)
        system_prompt += f"\n\n[사용자가 저장한 태그 정보]\n{tag_info}"
        print(f"📌 태그 컨텍스트 {len(tag_context)}개 참조")

    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=conversation_history,
        system=system_prompt
    )

    response = message.content[0].text

    conversation_history.append({"role": "assistant", "content": response})
    save_to_supabase("assistant", response)
    save_history(conversation_history)

    return response

def main():
    global pending_tag_info
    print("=" * 50)
    print("🤖 AI 음성 비서 - 오 비서")
    print("🧠 Mem0 스마트 기억 활성화!")
    print("=" * 50)
    print("📌 '오 비서'라고 불러주세요!")
    print("=" * 50)

    token = get_access_token()
    print("✅ 리턴제로 인증 완료!")

    while True:
        try:
            if listen_for_wake_word(token):
                text_to_speech("네, 말씀하세요")

                while True:
                    time.sleep(0.3)
                    record_command()
                    print("🔄 음성 인식 중...")
                    question = speech_to_text_stt(token)

                    if question:
                        if any(word in question for word in ["종료", "그만", "끝", "잘가"]):
                            text_to_speech("네, 다음에 또 불러주세요!")
                            pending_tag_info = None
                            break

                        print(f"\n📝 인식된 텍스트: {question}")

                        if pending_tag_info:
                            if any(word in question for word in ["응", "네", "좋아", "그래", "해줘", "저장", "예"]):
                                saved = save_to_tag(pending_tag_info["tag_name"], pending_tag_info["content"])
                                if saved:
                                    text_to_speech(f"'{saved}' 태그에 저장했어요!")
                                else:
                                    text_to_speech("저장에 실패했어요.")
                                pending_tag_info = None
                                continue
                            elif any(word in question for word in ["아니", "싫어", "됐어", "괜찮아", "안해"]):
                                text_to_speech("알겠어요, 저장하지 않을게요.")
                                pending_tag_info = None
                                continue
                            else:
                                pending_tag_info = None

                        tag_response = process_tag_command(question, conversation_history[-4:] if len(conversation_history) >= 4 else conversation_history)
                        if tag_response:
                            text_to_speech(tag_response)
                            continue

                        ai_choice = classify_question(question)
                        print(f"🎯 선택된 AI: {ai_choice}")

                        if ai_choice == "gemini":
                            response = ask_gemini(question)
                        else:
                            response = ask_claude(question)

                        text_to_speech(response)

                        detected = detect_important_info(question)
                        if detected:
                            pending_tag_info = detected
                            tag_name = detected["tag_name"]
                            text_to_speech(f"'{tag_name}' 태그에 저장할까요?")
                            print(f"🏷️ 자동 태깅 감지: {tag_name} - {detected['extracted']}")

                    else:
                        print("(조용함 감지, 대화 종료)")
                        pending_tag_info = None
                        break

        except KeyboardInterrupt:
            print("\n👋 종료합니다!")
            break
        except Exception as e:
            print(f"오류: {e}")
            continue

if __name__ == "__main__":
    main()
