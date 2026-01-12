import logging
import os

# 모든 로그 숨기기
logging.basicConfig(level=logging.CRITICAL)
logging.getLogger().setLevel(logging.CRITICAL)

# 모든 라이브러리 로그 숨기기
for name in [
    "livekit",
    "livekit.agents",
    "livekit.plugins",
    "hpack",
    "hpack.hpack",
    "hpack.table",
    "httpx",
    "httpcore",
    "asyncio",
    "watchfiles",
]:
    logging.getLogger(name).setLevel(logging.CRITICAL)

# 환경 변수로도 설정
os.environ["LIVEKIT_LOG_LEVEL"] = "error"

from difflib import SequenceMatcher

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    cli,
    inference,
    room_io,
)
from livekit.plugins import noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from mem0 import MemoryClient
from supabase import create_client

logger = logging.getLogger("agent")
logger.setLevel(logging.INFO)

load_dotenv(".env.local")

# ============ Supabase 설정 ============
SUPABASE_URL = "https://sbvobbxpsipzqmfhmbqh.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNidm9iYnhwc2lwenFtZmhtYnFoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjgwNDY3MDMsImV4cCI6MjA4MzYyMjcwM30.th34DFEfBS0hp2XdkJBpsVNIlQfbosK4f3W-rYTWIzI"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============ Mem0 설정 ============
MEM0_API_KEY = "m0-iEea9g88vKEmCS8jVD9aw1S1uHgjjexukn9qvV6r"
MEM0_USER_ID = "junseok"
mem0_client = MemoryClient(api_key=MEM0_API_KEY)


# ============ Mem0 함수들 ============
def search_mem0_memories(limit: int = 10) -> str:
    """Mem0에서 기억들 검색"""
    try:
        results = mem0_client.search(
            query="사용자 정보",
            filters={"user_id": MEM0_USER_ID},
            limit=limit
        )
        if results and results.get("results"):
            memory_lines = []
            for mem in results["results"]:
                memory_lines.append(f"- {mem['memory']}")
            if memory_lines:
                logger.info(f"[Memory] 로드됨: {memory_lines}")
                return "\n".join(memory_lines)
    except Exception as e:
        logger.error(f"Mem0 검색 오류: {e}")
    return ""


# ============ Supabase 대화 기록 함수 ============
def load_from_supabase(limit: int = 10) -> list[dict]:
    """Supabase에서 최근 대화 불러오기"""
    try:
        response = (
            supabase.table("conversations")
            .select("role, content")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        if response.data:
            conversations = list(reversed(response.data))
            return [{"role": c["role"], "content": c["content"]} for c in conversations]
    except Exception as e:
        logger.error(f"Supabase 불러오기 오류: {e}")
    return []


def save_to_supabase(role: str, content: str) -> None:
    """Supabase에 대화 저장"""
    try:
        supabase.table("conversations").insert(
            {"role": role, "content": content, "source": "livekit"}
        ).execute()
        logger.info(f"대화 저장됨: {role}")
    except Exception as e:
        logger.error(f"Supabase 저장 오류: {e}")


# ============ Supabase 태그 함수 ============
def normalize_tag(tag: str) -> str:
    """태그 이름 정규화 (발음 유사도 대응)"""
    tag = tag.lower().replace(" ", "").replace(".", "")
    replacements = {
        "에이": "a",
        "비": "b",
        "씨": "c",
        "디": "d",
        "이": "e",
        "에프": "f",
        "지": "g",
        "에이치": "h",
        "아이": "i",
        "제이": "j",
        "케이": "k",
        "엘": "l",
        "엠": "m",
        "엔": "n",
        "오": "o",
        "피": "p",
        "큐": "q",
        "알": "r",
        "에스": "s",
        "티": "t",
        "유": "u",
        "브이": "v",
        "더블유": "w",
        "엑스": "x",
        "와이": "y",
        "제트": "z",
    }
    for kor, eng in replacements.items():
        tag = tag.replace(kor, eng)
    return tag


def get_all_tags() -> list[str]:
    """Supabase에서 모든 태그 목록 가져오기"""
    try:
        response = supabase.table("tags").select("tag_name").execute()
        if response.data:
            return list({item["tag_name"] for item in response.data})
    except Exception as e:
        logger.error(f"태그 목록 조회 오류: {e}")
    return []


def find_similar_tag(tag_name: str) -> str | None:
    """유사한 태그 찾기"""
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


def search_tag(tag_name: str) -> tuple[str | None, list]:
    """Supabase에서 태그 검색"""
    similar = find_similar_tag(tag_name)
    if not similar:
        return None, []

    try:
        response = (
            supabase.table("tags")
            .select("*")
            .eq("tag_name", similar)
            .order("created_at", desc=True)
            .execute()
        )
        return similar, response.data if response.data else []
    except Exception as e:
        logger.error(f"태그 검색 오류: {e}")
        return similar, []


def get_tag_context() -> str:
    """모든 태그 내용 가져와서 컨텍스트 문자열 생성"""
    try:
        response = (
            supabase.table("tags")
            .select("tag_name, content")
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        if response.data:
            tag_lines = []
            for item in response.data:
                tag_name = item.get("tag_name", "")
                content = item.get("content", "")
                tag_lines.append(f"[{tag_name}] {content}")
            return "\n".join(tag_lines)
    except Exception as e:
        logger.error(f"태그 컨텍스트 조회 오류: {e}")
    return ""


def get_recent_conversation_summary() -> str:
    """최근 대화 요약 가져오기"""
    conversations = load_from_supabase(limit=6)
    if not conversations:
        return ""

    summary_lines = []
    for conv in conversations:
        role = "준석님" if conv["role"] == "user" else "오비서"
        content = conv["content"][:100]  # 최대 100자
        summary_lines.append(f"{role}: {content}")

    return "\n".join(summary_lines)


def build_system_prompt() -> str:
    """시스템 프롬프트 생성 (기본 역할 + 태그 컨텍스트 + 최근 대화)"""
    base_prompt = """당신은 '오 비서'라는 이름의 개인 AI 비서입니다.

역할:
- 24시간 준석님을 도와드리는 전담 비서
- 일정, 메모, 할 일 관리
- 다양한 질문에 친절하게 답변

말투 규칙 (매우 중요):
- 항상 존댓말을 사용하세요
- 사용자를 "준석님"이라고 호칭하세요
- 친근하지만 예의바른 톤을 유지하세요
- 예시: "네, 준석님! ~해드릴게요", "알겠습니다, 준석님", "준석님, ~하시면 좋을 것 같아요"

성격:
- 정중하고 친근한 비서 스타일
- 짧고 핵심적으로 답변
- 이모지나 특수문자는 사용하지 않음

규칙:
- 항상 한국어로 대답
- 모르는 것은 솔직하게 모른다고 말하기
- "종료"라고 하시면 "네, 준석님! 다음에 또 불러주세요"라고 응답"""

    # Mem0 기억 추가
    mem0_context = search_mem0_memories(limit=30)
    if mem0_context:
        base_prompt += f"""

[준석님에 대해 기억하고 있는 정보]
{mem0_context}

위 기억을 참고하여 개인화된 답변을 해주세요."""

    # 태그 컨텍스트 추가
    tag_context = get_tag_context()
    if tag_context:
        base_prompt += f"""

[준석님이 저장하신 정보]
{tag_context}

위 정보를 참고하여 답변해주세요."""

    # 최근 대화 추가
    recent_conv = get_recent_conversation_summary()
    if recent_conv:
        base_prompt += f"""

[최근 대화 기록]
{recent_conv}

위 대화 맥락을 고려하여 자연스럽게 이어서 답변해주세요."""

    return base_prompt


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=build_system_prompt(),
        )


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # 에이전트 인스턴스 생성 (나중에 업데이트하기 위해 변수로 저장)
    assistant = Assistant()

    session = AgentSession(
        stt=inference.STT(model="deepgram/nova-3", language="ko"),
        llm=inference.LLM(model="google/gemini-2.0-flash"),
        tts=inference.TTS(
            model="cartesia/sonic-3", voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    # Supabase 대화 저장용 이벤트 핸들러
    @session.on("user_input_transcribed")
    def on_user_input(event):
        """사용자 입력이 전사되었을 때 - Supabase에 저장"""
        if hasattr(event, "transcript") and event.transcript:
            save_to_supabase("user", event.transcript)
            logger.info(f"사용자 입력: {event.transcript[:50]}...")

    @session.on("agent_speech_committed")
    def on_agent_speech(event):
        """에이전트 응답 완료 시 - Supabase에 저장"""
        if hasattr(event, "content") and event.content:
            save_to_supabase("assistant", event.content)
            logger.info(f"에이전트 응답: {event.content[:50]}...")

    await session.start(
        agent=assistant,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
