import os
import tempfile
import logging
from typing import Optional, List
from backend.models.schema import AudioTranscript, AudioSegment

logger = logging.getLogger(__name__)

_WHISPER_MODEL = None

def get_whisper_model(model_size: str = "base"):
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        try:
            from faster_whisper import WhisperModel
            logger.info(f"Loading Faster-Whisper model ({model_size})...")
            _WHISPER_MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
        except ImportError:
            logger.warning("faster-whisper not installed. Falling back to basic audio mode.")
            _WHISPER_MODEL = False
        except Exception as e:
            logger.error(f"Error loading whisper model: {e}")
            _WHISPER_MODEL = False
    return _WHISPER_MODEL

class AudioTranscriber:
    def __init__(self, model_size: str = "base"):
        self.model_size = model_size

    def extract_audio_wav(self, video_path: str, output_wav_path: str) -> bool:
        """Extracts mono 16kHz audio WAV track from video using PyAV (libav)."""
        try:
            import av

            container = av.open(video_path)
            audio_streams = [s for s in container.streams if s.type == 'audio']
            if not audio_streams:
                logger.info(f"No audio stream found in {video_path}")
                return False

            resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
            
            with av.open(output_wav_path, 'w', format='wav') as out_container:
                out_stream = out_container.add_stream('pcm_s16le', rate=16000)
                out_stream.layout = 'mono'

                for frame in container.decode(audio=0):
                    resampled_frames = resampler.resample(frame)
                    for r_frame in resampled_frames:
                        for packet in out_stream.encode(r_frame):
                            out_container.mux(packet)

                for packet in out_stream.encode(None):
                    out_container.mux(packet)
            
            return os.path.exists(output_wav_path) and os.path.getsize(output_wav_path) > 0
        except Exception as e:
            logger.error(f"Error extracting audio with PyAV: {e}")
            return False

    def transcribe(self, video_path: str) -> AudioTranscript:
        """Main method to extract audio and transcribe Turkish speech."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            tmp_wav = tmp_file.name

        try:
            has_audio = self.extract_audio_wav(video_path, tmp_wav)
            if not has_audio:
                return AudioTranscript(
                    full_text="[Videoda ses / konuşma bulunamadı]",
                    language="tr",
                    segments=[],
                    has_speech=False
                )

            model = get_whisper_model(self.model_size)
            if not model:
                return AudioTranscript(
                    full_text="[Whisper modeli yüklenemedi - Ses aktiftir]",
                    language="tr",
                    segments=[],
                    has_speech=True
                )

            # Explicitly force Turkish language for maximum accuracy on Turkish dialogues
            segments, info = model.transcribe(tmp_wav, language="tr", beam_size=5, vad_filter=True)
            
            parsed_segments: List[AudioSegment] = []
            full_text_list = []

            for seg in segments:
                text = seg.text.strip()
                if text:
                    parsed_segments.append(AudioSegment(
                        start_time=round(seg.start, 2),
                        end_time=round(seg.end, 2),
                        text=text
                    ))
                    full_text_list.append(text)

            full_text = " ".join(full_text_list)

            return AudioTranscript(
                full_text=full_text if full_text else "[Konuşma tespit edilmedi - Arka plan sesi var]",
                language="tr",
                segments=parsed_segments,
                has_speech=len(parsed_segments) > 0
            )

        except Exception as e:
            logger.error(f"Transcription failed for {video_path}: {e}")
            return AudioTranscript(
                full_text=f"[Transkripsiyon hatası: {str(e)}]",
                language="tr",
                segments=[],
                has_speech=False
            )
        finally:
            if os.path.exists(tmp_wav):
                try:
                    os.remove(tmp_wav)
                except Exception:
                    pass
