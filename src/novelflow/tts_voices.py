"""Voice catalog for Edge online neural TTS."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceOption:
    id: str
    label: str
    engine: str
    locale: str = "en-US"


EDGE_VOICES: tuple[VoiceOption, ...] = (
    VoiceOption("en-US-AriaNeural", "Aria (US female)", "edge", "en-US"),
    VoiceOption("en-US-GuyNeural", "Guy (US male)", "edge", "en-US"),
    VoiceOption("en-US-JennyNeural", "Jenny (US female)", "edge", "en-US"),
    VoiceOption("en-US-AndrewNeural", "Andrew (US male)", "edge", "en-US"),
    VoiceOption("en-US-AvaNeural", "Ava (US female)", "edge", "en-US"),
    VoiceOption("en-US-BrianNeural", "Brian (US male)", "edge", "en-US"),
    VoiceOption("en-US-EmmaNeural", "Emma (US female)", "edge", "en-US"),
    VoiceOption("en-US-ChristopherNeural", "Christopher (US male)", "edge", "en-US"),
    VoiceOption("en-GB-SoniaNeural", "Sonia (UK female)", "edge", "en-GB"),
    VoiceOption("en-GB-RyanNeural", "Ryan (UK male)", "edge", "en-GB"),
    VoiceOption("en-GB-LibbyNeural", "Libby (UK female)", "edge", "en-GB"),
    VoiceOption("en-AU-NatashaNeural", "Natasha (AU female)", "edge", "en-AU"),
    VoiceOption("en-AU-WilliamNeural", "William (AU male)", "edge", "en-AU"),
    VoiceOption("en-IN-NeerjaNeural", "Neerja (IN female)", "edge", "en-IN"),
    VoiceOption("en-IN-PrabhatNeural", "Prabhat (IN male)", "edge", "en-IN"),
)

DEFAULT_VOICE = "en-US-AriaNeural"


def default_voice(engine: str = "edge") -> str:
    return DEFAULT_VOICE


def voices_for_engine(engine: str = "edge") -> tuple[VoiceOption, ...]:
    return EDGE_VOICES


def voice_label(engine: str, voice_id: str) -> str:
    for voice in EDGE_VOICES:
        if voice.id == voice_id:
            return voice.label
    return voice_id
