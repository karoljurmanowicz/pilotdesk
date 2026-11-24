"""PilotDesk – wideo H.264 i dźwięk (Opus) przez PyAV, przechwytywanie/odtwarzanie dźwięku przez soundcard.
Wszystko jest opcjonalne: gdy biblioteki brakuje, program wraca do obrazu JPEG i wyłącza dźwięk."""
import queue
import sys
import threading
import time
from fractions import Fraction

try:
    import av
    import numpy as np
    _AV = True
except Exception:
    _AV = False

ENCODERS = ("libx264", "h264_mf", "h264_nvenc", "h264_qsv", "h264_amf")


def h264_encoder_name():
    if not _AV:
        return None
    for n in ENCODERS:
        if n in av.codecs_available:
            return n
    return None


def h264_decoder_ok():
    return _AV and "h264" in av.codecs_available


def opus_ok():
    return _AV and ("libopus" in av.codecs_available or "opus" in av.codecs_available)


def _set_keyframe(frame):
    try:
        frame.pict_type = av.video.frame.PictureType.I
    except Exception:
        try:
            frame.pict_type = "I"
        except Exception:
            pass


class VideoEncoder:
    """Koder H.264 z ustawieniami niskiego opóźnienia (bez klatek B, nagłówki w każdej klatce kluczowej)."""

    def __init__(self, width, height, fps, bitrate):
        self.w, self.h = width - width % 2, height - height % 2
        self.ctx = None
        self.name = None
        last = None
        for name in ENCODERS:
            if name not in av.codecs_available:
                continue
            try:
                ctx = av.CodecContext.create(name, "w")
                ctx.width, ctx.height = self.w, self.h
                ctx.pix_fmt = "yuv420p" if name != "h264_mf" else "nv12"
                ctx.time_base = Fraction(1, 1000)
                ctx.framerate = Fraction(int(fps), 1)
                ctx.bit_rate = int(bitrate)
                ctx.gop_size = int(fps) * 20
                ctx.max_b_frames = 0
                if name == "libx264":
                    ctx.options = {"preset": "ultrafast", "tune": "zerolatency",
                                   "x264-params": "bframes=0:scenecut=0:repeat-headers=1:rc-lookahead=0:sync-lookahead=0"}
                elif name == "h264_mf":
                    ctx.options = {"rate_control": "cbr", "scenario": "display_remoting", "hw_encoding": "1"}
                elif name == "h264_nvenc":
                    ctx.options = {"preset": "p1", "tune": "ull", "zerolatency": "1", "delay": "0"}
                elif name == "h264_qsv":
                    ctx.options = {"preset": "veryfast", "async_depth": "1", "low_power": "1"}
                elif name == "h264_amf":
                    ctx.options = {"usage": "ultralowlatency", "quality": "speed"}
                ctx.open()
                self.ctx, self.name = ctx, name
                break
            except Exception as e:
                last = e
        if self.ctx is None:
            raise RuntimeError(f"brak kodera H.264 ({last})")
        self.t0 = time.time()
        self.force_key = True

    def encode(self, rgb):
        """rgb: tablica numpy H×W×3. Zwraca (bajty, czy_kluczowa)."""
        if rgb.shape[1] != self.w or rgb.shape[0] != self.h:
            rgb = rgb[:self.h, :self.w]
        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(rgb), format="rgb24")
        frame = frame.reformat(format=self.ctx.pix_fmt)
        frame.pts = int((time.time() - self.t0) * 1000)
        if self.force_key:
            _set_keyframe(frame)
            self.force_key = False
        data, key = [], False
        for p in self.ctx.encode(frame):
            data.append(bytes(p))
            key = key or p.is_keyframe
        return b"".join(data), key

    def close(self):
        try:
            self.ctx.encode(None)
        except Exception:
            pass


class VideoDecoder:
    def __init__(self):
        self.ctx = av.CodecContext.create("h264", "r")
        try:
            self.ctx.thread_type = "NONE"  # najmniejsze opóźnienie
        except Exception:
            pass

    def decode(self, data):
        """Zwraca ostatnią zdekodowaną klatkę jako obraz PIL (RGB) albo None."""
        img = None
        for f in self.ctx.decode(av.Packet(data)):
            img = f.to_image()
        return img


# --------------------------------------------------------------------------- dźwięk

RATE = 48000
FRAME = 960  # 20 ms


class AudioEncoder:
    def __init__(self, bitrate=96000):
        name = "libopus" if "libopus" in av.codecs_available else "opus"
        self.ctx = av.CodecContext.create(name, "w")
        self.ctx.sample_rate = RATE
        try:
            self.ctx.layout = "stereo"
        except Exception:
            self.ctx.channels = 2
        self.ctx.format = "flt" if name == "libopus" else "fltp"
        self.ctx.bit_rate = bitrate
        try:
            self.ctx.options = {"application": "lowdelay", "frame_duration": "20"}
        except Exception:
            pass
        self.ctx.open()
        self.planar = self.ctx.format.name.endswith("p")
        self.pts = 0

    def encode(self, pcm):
        """pcm: float32 (FRAME, 2). Zwraca listę pakietów (bajty)."""
        if self.planar:
            frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(pcm.T, dtype=np.float32), format="fltp",
                                               layout="stereo")
        else:
            frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(pcm, dtype=np.float32).reshape(1, -1),
                                               format="flt", layout="stereo")
        frame.sample_rate = RATE
        frame.pts = self.pts
        self.pts += pcm.shape[0]
        return [bytes(p) for p in self.ctx.encode(frame)]


class AudioDecoder:
    def __init__(self):
        name = "libopus" if "libopus" in av.codecs_available else "opus"
        self.ctx = av.CodecContext.create(name, "r")
        self.ctx.sample_rate = RATE
        try:
            self.ctx.layout = "stereo"
        except Exception:
            pass

    def decode(self, data):
        out = []
        for f in self.ctx.decode(av.Packet(data)):
            a = f.to_ndarray()
            if f.format.is_planar:
                a = a.T
            else:
                a = a.reshape(-1, len(f.layout.channels))
            if a.shape[1] == 1:
                a = np.repeat(a, 2, axis=1)
            if a.dtype == np.int16:
                a = a.astype(np.float32) / 32768.0
            elif a.dtype == np.int32:
                a = a.astype(np.float32) / 2147483648.0
            out.append(a.astype(np.float32))
        return out


def audio_capture_ok():
    try:
        import soundcard  # noqa
        return opus_ok()
    except Exception:
        return False


class AudioStreamer:
    """Strona sterowana: nagrywa dźwięk systemu (loopback) i wysyła pakiety Opus przez send(bajty)."""

    def __init__(self, send, log=print):
        self.send = send
        self.log = log
        self.running = False

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running = False

    def _run(self):
        try:
            import soundcard as sc
            if sys.platform == "win32":
                try:
                    import pythoncom
                    pythoncom.CoInitialize()
                except Exception:
                    pass
            spk = sc.default_speaker()
            mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
            enc = AudioEncoder()
            with mic.recorder(samplerate=RATE, channels=2, blocksize=FRAME) as rec:
                while self.running:
                    pcm = rec.record(numframes=FRAME)
                    if pcm.shape[0] != FRAME:
                        continue
                    if not np.any(np.abs(pcm) > 1e-4):
                        continue  # cisza – nic nie wysyłamy
                    for pkt in enc.encode(pcm):
                        self.send(pkt)
        except Exception as e:
            self.log(f"Dźwięk niedostępny: {e}")
        finally:
            self.running = False


class AudioPlayer:
    """Strona przeglądająca: dekoduje i odtwarza dźwięk z małym buforem (opóźnienie ~60–100 ms)."""

    def __init__(self):
        self.q = queue.Queue(maxsize=50)
        self.running = False
        self.dec = AudioDecoder()
        self.volume = 1.0

    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running = False

    def feed(self, data):
        if not self.running:
            return
        try:
            for pcm in self.dec.decode(data):
                if self.q.qsize() > 10:  # za duże opóźnienie – gubimy najstarsze
                    try:
                        self.q.get_nowait()
                    except queue.Empty:
                        pass
                self.q.put_nowait(pcm)
        except Exception:
            pass

    def _run(self):
        try:
            import soundcard as sc
            if sys.platform == "win32":
                try:
                    import pythoncom
                    pythoncom.CoInitialize()
                except Exception:
                    pass
            with sc.default_speaker().player(samplerate=RATE, channels=2, blocksize=FRAME) as p:
                silence = np.zeros((FRAME, 2), dtype=np.float32)
                while self.running:
                    try:
                        pcm = self.q.get(timeout=0.1)
                        p.play(pcm * self.volume)
                    except queue.Empty:
                        p.play(silence)
        except Exception:
            self.running = False
