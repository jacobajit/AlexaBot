import os
import tornado.httpserver
import tornado.ioloop
import tornado.web
import tornado.template
from creds import *
from requests import Request
import requests
import json
import re
import tempfile
import redis
import uuid
import string
from pydub import AudioSegment
# import speech_recognition as sr
from pymessenger.bot import Bot
import traceback
import urllib2

#pydub imports
import io, subprocess, wave, aifc, base64
import math, audioop, collections, threading
import platform, stat, random, uuid

from timeout_dec import timeout_dec  # timeout decorator


TOKEN= Facebook_Token
bot = Bot(TOKEN)


# define exceptions
class TimeoutError(Exception): pass
class RequestError(Exception): pass
class UnknownValueError(Exception): pass

class AudioSource(object):
    def __init__(self):
        raise NotImplementedError("this is an abstract class")

    def __enter__(self):
        raise NotImplementedError("this is an abstract class")

    def __exit__(self, exc_type, exc_value, traceback):
        raise NotImplementedError("this is an abstract class")


class AudioFile(AudioSource):
    """
    Creates a new ``AudioFile`` instance given a WAV/AIFF/FLAC audio file `filename_or_fileobject`. Subclass of ``AudioSource``.
    If ``filename_or_fileobject`` is a string, then it is interpreted as a path to an audio file on the filesystem. Otherwise, ``filename_or_fileobject`` should be a file-like object such as ``io.BytesIO`` or similar.
    Note that functions that read from the audio (such as ``recognizer_instance.record`` or ``recognizer_instance.listen``) will move ahead in the stream. For example, if you execute ``recognizer_instance.record(audiofile_instance, duration=10)`` twice, the first time it will return the first 10 seconds of audio, and the second time it will return the 10 seconds of audio right after that. This is always reset to the beginning when entering an ``AudioFile`` context.
    WAV files must be in PCM/LPCM format; WAVE_FORMAT_EXTENSIBLE and compressed WAV are not supported and may result in undefined behaviour.
    Both AIFF and AIFF-C (compressed AIFF) formats are supported.
    FLAC files must be in native FLAC format; OGG-FLAC is not supported and may result in undefined behaviour.
    """

    def __init__(self, filename_or_fileobject):
        if str is bytes: # Python 2 - if a file path is specified, it must either be a `str` instance or a `unicode` instance
            assert isinstance(filename_or_fileobject, (str, unicode)) or hasattr(filename_or_fileobject, "read"), "Given audio file must be a filename string or a file-like object"
        else: # Python 3 - if a file path is specified, it must be a `str` instance
            assert isinstance(filename_or_fileobject, str) or hasattr(filename_or_fileobject, "read"), "Given audio file must be a filename string or a file-like object"
        self.filename_or_fileobject = filename_or_fileobject
        self.stream = None
        self.DURATION = None

    def __enter__(self):
        assert self.stream is None, "This audio source is already inside a context manager"
        try:
            # attempt to read the file as WAV
            self.audio_reader = wave.open(self.filename_or_fileobject, "rb")
            self.little_endian = True # RIFF WAV is a little-endian format (most ``audioop`` operations assume that the frames are stored in little-endian form)
        except wave.Error:
            try:
                # attempt to read the file as AIFF
                self.audio_reader = aifc.open(self.filename_or_fileobject, "rb")
                self.little_endian = False # AIFF is a big-endian format
            except aifc.Error:
                # attempt to read the file as FLAC
                if hasattr(self.filename_or_fileobject, "read"):
                    flac_data = self.filename_or_fileobject.read()
                else:
                    with open(self.filename_or_fileobject, "rb") as f: flac_data = f.read()

                # run the FLAC converter with the FLAC data to get the AIFF data
                flac_converter = get_flac_converter()
                process = subprocess.Popen([
                    flac_converter,
                    "--stdout", "--totally-silent", # put the resulting AIFF file in stdout, and make sure it's not mixed with any program output
                    "--decode", "--force-aiff-format", # decode the FLAC file into an AIFF file
                    "-", # the input FLAC file contents will be given in stdin
                ], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
                aiff_data, stderr = process.communicate(flac_data)
                aiff_file = io.BytesIO(aiff_data)
                try:
                    self.audio_reader = aifc.open(aiff_file, "rb")
                except aifc.Error:
                    assert False, "Audio file could not be read as WAV, AIFF, or FLAC; check if file is corrupted"
                self.little_endian = False # AIFF is a big-endian format
        assert 1 <= self.audio_reader.getnchannels() <= 2, "Audio must be mono or stereo"
        self.SAMPLE_WIDTH = self.audio_reader.getsampwidth()

        # 24-bit audio needs some special handling for old Python versions (workaround for https://bugs.python.org/issue12866)
        samples_24_bit_pretending_to_be_32_bit = False
        if self.SAMPLE_WIDTH == 3: # 24-bit audio
            try: audioop.bias(b"", self.SAMPLE_WIDTH, 0) # test whether this sample width is supported (for example, ``audioop`` in Python 3.3 and below don't support sample width 3, while Python 3.4+ do)
            except audioop.error: # this version of audioop doesn't support 24-bit audio (probably Python 3.3 or less)
                samples_24_bit_pretending_to_be_32_bit = True # while the ``AudioFile`` instance will outwardly appear to be 32-bit, it will actually internally be 24-bit
                self.SAMPLE_WIDTH = 4 # the ``AudioFile`` instance should present itself as a 32-bit stream now, since we'll be converting into 32-bit on the fly when reading

        self.SAMPLE_RATE = self.audio_reader.getframerate()
        self.CHUNK = 4096
        self.FRAME_COUNT = self.audio_reader.getnframes()
        self.DURATION = self.FRAME_COUNT / float(self.SAMPLE_RATE)
        self.stream = AudioFile.AudioFileStream(self.audio_reader, self.little_endian, samples_24_bit_pretending_to_be_32_bit)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if not hasattr(self.filename_or_fileobject, "read"): # only close the file if it was opened by this class in the first place (if the file was originally given as a path)
            self.audio_reader.close()
        self.stream = None
        self.DURATION = None


    class AudioFileStream(object):
        def __init__(self, audio_reader, little_endian, samples_24_bit_pretending_to_be_32_bit):
            self.audio_reader = audio_reader # an audio file object (e.g., a `wave.Wave_read` instance)
            self.little_endian = little_endian # whether the audio data is little-endian (when working with big-endian things, we'll have to convert it to little-endian before we process it)
            self.samples_24_bit_pretending_to_be_32_bit = samples_24_bit_pretending_to_be_32_bit # this is true if the audio is 24-bit audio, but 24-bit audio isn't supported, so we have to pretend that this is 32-bit audio and convert it on the fly

        def read(self, size = -1):
            buffer = self.audio_reader.readframes(self.audio_reader.getnframes() if size == -1 else size)
            if not isinstance(buffer, bytes): buffer = b"" # workaround for https://bugs.python.org/issue24608

            sample_width = self.audio_reader.getsampwidth()
            if not self.little_endian: # big endian format, convert to little endian on the fly
                if hasattr(audioop, "byteswap"): # ``audioop.byteswap`` was only added in Python 3.4 (incidentally, that also means that we don't need to worry about 24-bit audio being unsupported, since Python 3.4+ always has that functionality)
                    buffer = audioop.byteswap(buffer, sample_width)
                else: # manually reverse the bytes of each sample, which is slower but works well enough as a fallback
                    buffer = buffer[sample_width - 1::-1] + b"".join(buffer[i + sample_width:i:-1] for i in range(sample_width - 1, len(buffer), sample_width))

            # workaround for https://bugs.python.org/issue12866
            if self.samples_24_bit_pretending_to_be_32_bit: # we need to convert samples from 24-bit to 32-bit before we can process them with ``audioop`` functions
                buffer = b"".join("\x00" + buffer[i:i + sample_width] for i in range(0, len(buffer), sample_width)) # since we're in little endian, we prepend a zero byte to each 24-bit sample to get a 32-bit sample
            if self.audio_reader.getnchannels() != 1: # stereo audio
                buffer = audioop.tomono(buffer, sample_width, 1, 1) # convert stereo audio data to mono
            return buffer


class AudioData(object):

    def __init__(self, frame_data, sample_rate, sample_width):
        assert sample_rate > 0, "Sample rate must be a positive integer"
        assert sample_width % 1 == 0 and 1 <= sample_width <= 4, "Sample width must be between 1 and 4 inclusive"
        self.frame_data = frame_data
        self.sample_rate = sample_rate
        self.sample_width = int(sample_width)

    def get_raw_data(self, convert_rate = None, convert_width = None):
        """
        Returns a byte string representing the raw frame data for the audio represented by the ``AudioData`` instance.
        If ``convert_rate`` is specified and the audio sample rate is not ``convert_rate`` Hz, the resulting audio is resampled to match.
        If ``convert_width`` is specified and the audio samples are not ``convert_width`` bytes each, the resulting audio is converted to match.
        Writing these bytes directly to a file results in a valid `RAW/PCM audio file <https://en.wikipedia.org/wiki/Raw_audio_format>`__.
        """
        assert convert_rate is None or convert_rate > 0, "Sample rate to convert to must be a positive integer"
        assert convert_width is None or (convert_width % 1 == 0 and 1 <= convert_width <= 4), "Sample width to convert to must be between 1 and 4 inclusive"

        raw_data = self.frame_data

        # make sure unsigned 8-bit audio (which uses unsigned samples) is handled like higher sample width audio (which uses signed samples)
        if self.sample_width == 1:
            raw_data = audioop.bias(raw_data, 1, -128) # subtract 128 from every sample to make them act like signed samples

        # resample audio at the desired rate if specified
        if convert_rate is not None and self.sample_rate != convert_rate:
            raw_data, _ = audioop.ratecv(raw_data, self.sample_width, 1, self.sample_rate, convert_rate, None)

        # convert samples to desired sample width if specified
        if convert_width is not None and self.sample_width != convert_width:
            if convert_width == 3: # we're converting the audio into 24-bit (workaround for https://bugs.python.org/issue12866)
                raw_data = audioop.lin2lin(raw_data, self.sample_width, 4) # convert audio into 32-bit first, which is always supported
                try: audioop.bias(b"", 3, 0) # test whether 24-bit audio is supported (for example, ``audioop`` in Python 3.3 and below don't support sample width 3, while Python 3.4+ do)
                except audioop.error: # this version of audioop doesn't support 24-bit audio (probably Python 3.3 or less)
                    raw_data = b"".join(raw_data[i + 1:i + 4] for i in range(0, len(raw_data), 4)) # since we're in little endian, we discard the first byte from each 32-bit sample to get a 24-bit sample
                else: # 24-bit audio fully supported, we don't need to shim anything
                    raw_data = audioop.lin2lin(raw_data, self.sample_width, convert_width)
            else:
                raw_data = audioop.lin2lin(raw_data, self.sample_width, convert_width)

        # if the output is 8-bit audio with unsigned samples, convert the samples we've been treating as signed to unsigned again
        if convert_width == 1:
            raw_data = audioop.bias(raw_data, 1, 128) # add 128 to every sample to make them act like unsigned samples again

        return raw_data

    def get_wav_data(self, convert_rate = None, convert_width = None):
        """
        Returns a byte string representing the contents of a WAV file containing the audio represented by the ``AudioData`` instance.
        If ``convert_width`` is specified and the audio samples are not ``convert_width`` bytes each, the resulting audio is converted to match.
        If ``convert_rate`` is specified and the audio sample rate is not ``convert_rate`` Hz, the resulting audio is resampled to match.
        Writing these bytes directly to a file results in a valid `WAV file <https://en.wikipedia.org/wiki/WAV>`__.
        """
        raw_data = self.get_raw_data(convert_rate, convert_width)
        sample_rate = self.sample_rate if convert_rate is None else convert_rate
        sample_width = self.sample_width if convert_width is None else convert_width

        # generate the WAV file contents
        with io.BytesIO() as wav_file:
            wav_writer = wave.open(wav_file, "wb")
            try: # note that we can't use context manager, since that was only added in Python 3.4
                wav_writer.setframerate(sample_rate)
                wav_writer.setsampwidth(sample_width)
                wav_writer.setnchannels(1)
                wav_writer.writeframes(raw_data)
                wav_data = wav_file.getvalue()
            finally:  # make sure resources are cleaned up
                wav_writer.close()
        return wav_data


class Recognizer(AudioSource):
    def __init__(self):
        """
        Creates a new ``Recognizer`` instance, which represents a collection of speech recognition functionality.
        """
        self.energy_threshold = 300 # minimum audio energy to consider for recording
        self.dynamic_energy_threshold = True
        self.dynamic_energy_adjustment_damping = 0.15
        self.dynamic_energy_ratio = 1.5
        self.pause_threshold = 0.8 # seconds of non-speaking audio before a phrase is considered complete
        self.phrase_threshold = 0.3 # minimum seconds of speaking audio before we consider the speaking audio a phrase - values below this are ignored (for filtering out clicks and pops)
        self.non_speaking_duration = 0.5 # seconds of non-speaking audio to keep on both sides of the recording

    def record(self, source, duration = None, offset = None):
        """
        Records up to ``duration`` seconds of audio from ``source`` (an ``AudioSource`` instance) starting at ``offset`` (or at the beginning if not specified) into an ``AudioData`` instance, which it returns.
        If ``duration`` is not specified, then it will record until there is no more audio input.
        """
        assert isinstance(source, AudioSource), "Source must be an audio source"
        assert source.stream is not None, "Audio source must be entered before recording, see documentation for `AudioSource`; are you using `source` outside of a `with` statement?"

        frames = io.BytesIO()
        seconds_per_buffer = (source.CHUNK + 0.0) / source.SAMPLE_RATE
        elapsed_time = 0
        offset_time = 0
        offset_reached = False
        while True: # loop for the total number of chunks needed
            if offset and not offset_reached:
                offset_time += seconds_per_buffer
                if offset_time > offset:
                    offset_reached = True

            buffer = source.stream.read(source.CHUNK)
            if len(buffer) == 0: break

            if offset_reached or not offset:
                elapsed_time += seconds_per_buffer
                if duration and elapsed_time > duration: break

                frames.write(buffer)

        frame_data = frames.getvalue()
        frames.close()
        return AudioData(frame_data, source.SAMPLE_RATE, source.SAMPLE_WIDTH)

    def adjust_for_ambient_noise(self, source, duration = 1):
        """
        Adjusts the energy threshold dynamically using audio from ``source`` (an ``AudioSource`` instance) to account for ambient noise.
        Intended to calibrate the energy threshold with the ambient energy level. Should be used on periods of audio without speech - will stop early if any speech is detected.
        The ``duration`` parameter is the maximum number of seconds that it will dynamically adjust the threshold for before returning. This value should be at least 0.5 in order to get a representative sample of the ambient noise.
        """
        assert isinstance(source, AudioSource), "Source must be an audio source"
        assert source.stream is not None, "Audio source must be entered before adjusting, see documentation for `AudioSource`; are you using `source` outside of a `with` statement?"
        assert self.pause_threshold >= self.non_speaking_duration >= 0

        seconds_per_buffer = (source.CHUNK + 0.0) / source.SAMPLE_RATE
        elapsed_time = 0

        # adjust energy threshold until a phrase starts
        while True:
            elapsed_time += seconds_per_buffer
            if elapsed_time > duration: break
            buffer = source.stream.read(source.CHUNK)
            energy = audioop.rms(buffer, source.SAMPLE_WIDTH) # energy of the audio signal

            # dynamically adjust the energy threshold using assymmetric weighted average
            damping = self.dynamic_energy_adjustment_damping ** seconds_per_buffer # account for different chunk sizes and rates
            target_energy = energy * self.dynamic_energy_ratio
            self.energy_threshold = self.energy_threshold * damping + target_energy * (1 - damping)

    def listen(self, source, timeout = None):
        """
        Records a single phrase from ``source`` (an ``AudioSource`` instance) into an ``AudioData`` instance, which it returns.
        This is done by waiting until the audio has an energy above ``recognizer_instance.energy_threshold`` (the user has started speaking), and then recording until it encounters ``recognizer_instance.pause_threshold`` seconds of non-speaking or there is no more audio input. The ending silence is not included.
        The ``timeout`` parameter is the maximum number of seconds that it will wait for a phrase to start before giving up and throwing an ``speech_recognition.WaitTimeoutError`` exception. If ``timeout`` is ``None``, it will wait indefinitely.
        """
        assert isinstance(source, AudioSource), "Source must be an audio source"
        assert source.stream is not None, "Audio source must be entered before listening, see documentation for `AudioSource`; are you using `source` outside of a `with` statement?"
        assert self.pause_threshold >= self.non_speaking_duration >= 0

        seconds_per_buffer = (source.CHUNK + 0.0) / source.SAMPLE_RATE
        pause_buffer_count = int(math.ceil(self.pause_threshold / seconds_per_buffer)) # number of buffers of non-speaking audio before the phrase is complete
        phrase_buffer_count = int(math.ceil(self.phrase_threshold / seconds_per_buffer)) # minimum number of buffers of speaking audio before we consider the speaking audio a phrase
        non_speaking_buffer_count = int(math.ceil(self.non_speaking_duration / seconds_per_buffer)) # maximum number of buffers of non-speaking audio to retain before and after

        # read audio input for phrases until there is a phrase that is long enough
        elapsed_time = 0 # number of seconds of audio read
        while True:
            frames = collections.deque()

            # store audio input until the phrase starts
            while True:
                elapsed_time += seconds_per_buffer
                if timeout and elapsed_time > timeout: # handle timeout if specified
                    raise TimeoutError("listening timed out")

                buffer = source.stream.read(source.CHUNK)
                if len(buffer) == 0: break # reached end of the stream
                frames.append(buffer)
                if len(frames) > non_speaking_buffer_count: # ensure we only keep the needed amount of non-speaking buffers
                    frames.popleft()

                # detect whether speaking has started on audio input
                energy = audioop.rms(buffer, source.SAMPLE_WIDTH) # energy of the audio signal
                if energy > self.energy_threshold: break

                # dynamically adjust the energy threshold using assymmetric weighted average
                if self.dynamic_energy_threshold:
                    damping = self.dynamic_energy_adjustment_damping ** seconds_per_buffer # account for different chunk sizes and rates
                    target_energy = energy * self.dynamic_energy_ratio
                    self.energy_threshold = self.energy_threshold * damping + target_energy * (1 - damping)

            # read audio input until the phrase ends
            pause_count, phrase_count = 0, 0
            while True:
                elapsed_time += seconds_per_buffer

                buffer = source.stream.read(source.CHUNK)
                if len(buffer) == 0: break # reached end of the stream
                frames.append(buffer)
                phrase_count += 1

                # check if speaking has stopped for longer than the pause threshold on the audio input
                energy = audioop.rms(buffer, source.SAMPLE_WIDTH) # energy of the audio signal
                if energy > self.energy_threshold:
                    pause_count = 0
                else:
                    pause_count += 1
                if pause_count > pause_buffer_count: # end of the phrase
                    break

            # check how long the detected phrase is, and retry listening if the phrase is too short
            phrase_count -= pause_count
            if phrase_count >= phrase_buffer_count: break # phrase is long enough, stop listening

        # obtain frame data
        for i in range(pause_count - non_speaking_buffer_count): frames.pop() # remove extra non-speaking frames at the end
        frame_data = b"".join(list(frames))

        return AudioData(frame_data, source.SAMPLE_RATE, source.SAMPLE_WIDTH)

    def listen_in_background(self, source, callback):
        """
        Spawns a thread to repeatedly record phrases from ``source`` (an ``AudioSource`` instance) into an ``AudioData`` instance and call ``callback`` with that ``AudioData`` instance as soon as each phrase are detected.
        Returns a function object that, when called, requests that the background listener thread stop, and waits until it does before returning. The background thread is a daemon and will not stop the program from exiting if there are no other non-daemon threads.
        Phrase recognition uses the exact same mechanism as ``recognizer_instance.listen(source)``.
        The ``callback`` parameter is a function that should accept two parameters - the ``recognizer_instance``, and an ``AudioData`` instance representing the captured audio. Note that ``callback`` function will be called from a non-main thread.
        """
        assert isinstance(source, AudioSource), "Source must be an audio source"
        running = [True]
        def threaded_listen():
            with source as s:
                while running[0]:
                    try: # listen for 1 second, then check again if the stop function has been called
                        audio = self.listen(s, 1)
                    except TimeoutError: # listening timed out, just try again
                        pass
                    else:
                        if running[0]: callback(self, audio)
        def stopper():
            running[0] = False
            listener_thread.join() # block until the background thread is done, which can be up to 1 second
        listener_thread = threading.Thread(target=threaded_listen)
        listener_thread.daemon = True
        listener_thread.start()
        return stopper

    def recognize_bing(self, audio_data, key, language = "en-US", show_all = False):
        """
        Performs speech recognition on ``audio_data`` (an ``AudioData`` instance), using the Microsoft Bing Voice Recognition API.
        The Microsoft Bing Voice Recognition API key is specified by ``key``. Unfortunately, these are not available without `signing up for an account <https://www.microsoft.com/cognitive-services/en-us/speech-api>`__ with Microsoft Cognitive Services.
        To get the API key, go to the `Microsoft Cognitive Services subscriptions overview <https://www.microsoft.com/cognitive-services/en-us/subscriptions>`__, go to the entry titled "Speech", and look for the key under the "Keys" column. Microsoft Bing Voice Recognition API keys are 32-character lowercase hexadecimal strings.
        The recognition language is determined by ``language``, an RFC5646 language tag like ``"en-US"`` (US English) or ``"fr-FR"`` (International French), defaulting to US English. A list of supported language values can be found in the `API documentation <https://www.microsoft.com/cognitive-services/en-us/speech-api/documentation/api-reference-rest/BingVoiceRecognition#user-content-4-supported-locales>`__.
        Returns the most likely transcription if ``show_all`` is false (the default). Otherwise, returns the `raw API response <https://www.microsoft.com/cognitive-services/en-us/speech-api/documentation/api-reference-rest/BingVoiceRecognition#user-content-3-voice-recognition-responses>`__ as a JSON dictionary.
        Raises a ``speech_recognition.UnknownValueError`` exception if the speech is unintelligible. Raises a ``speech_recognition.RequestError`` exception if the speech recognition operation failed, if the key isn't valid, or if there is no internet connection.
        """

        try: # attempt to use the Python 2 modules
            from urllib import urlencode
            from urllib2 import Request, urlopen, URLError, HTTPError
        except ImportError: # use the Python 3 modules
            from urllib.parse import urlencode
            from urllib.request import Request, urlopen
            from urllib.error import URLError, HTTPError


        assert isinstance(audio_data, AudioData), "Data must be audio data"
        assert isinstance(key, str), "`key` must be a string"
        assert isinstance(language, str), "`language` must be a string"

        access_token, expire_time = getattr(self, "bing_cached_access_token", None), getattr(self, "bing_cached_access_token_expiry", None)
        allow_caching = True
        try:
            from time import monotonic # we need monotonic time to avoid being affected by system clock changes, but this is only available in Python 3.3+
        except ImportError:
            try:
                from monotonic import monotonic # use time.monotonic backport for Python 2 if available (from https://pypi.python.org/pypi/monotonic)
            except (ImportError, RuntimeError):
                expire_time = None # monotonic time not available, don't cache access tokens
                allow_caching = False # don't allow caching, since monotonic time isn't available
        if expire_time is None or monotonic() > expire_time: # caching not enabled, first credential request, or the access token from the previous one expired
            # get an access token using OAuth
            credential_url = "https://oxford-speech.cloudapp.net/token/issueToken"
            credential_request = Request(credential_url, data = urlencode({
              "grant_type": "client_credentials",
              "client_id": "python",
              "client_secret": key,
              "scope": "https://speech.platform.bing.com"
            }).encode("utf-8"))
            if allow_caching:
                start_time = monotonic()
            try:
                credential_response = urlopen(credential_request)
            except HTTPError as e:
                raise RequestError("recognition request failed: {0}".format(getattr(e, "reason", "status {0}".format(e.code)))) # use getattr to be compatible with Python 2.6
            except URLError as e:
                raise RequestError("recognition connection failed: {0}".format(e.reason))
            credential_text = credential_response.read().decode("utf-8")
            credentials = json.loads(credential_text)
            access_token, expiry_seconds = credentials["access_token"], float(credentials["expires_in"])

            if allow_caching:
                # save the token for the duration it is valid for
                self.bing_cached_access_token = access_token
                self.bing_cached_access_token_expiry = start_time + expiry_seconds

        wav_data = audio_data.get_wav_data(
            convert_rate = 16000, # audio samples must be 8kHz or 16 kHz
            convert_width = 2 # audio samples should be 16-bit
        )
        url = "https://speech.platform.bing.com/recognize/query?{0}".format(urlencode({
            "version": "3.0",
            "requestid": uuid.uuid4(),
            "appID": "D4D52672-91D7-4C74-8AD8-42B1D98141A5",
            "format": "json",
            "locale": language,
            "device.os": "wp7",
            "scenarios": "ulm",
            "instanceid": uuid.uuid4(),
            "result.profanitymarkup": "0",
        }))
        request = Request(url, data = wav_data, headers = {
            "Authorization": "Bearer {0}".format(access_token),
            "Content-Type": "audio/wav; samplerate=16000; sourcerate={0}; trustsourcerate=true".format(audio_data.sample_rate),
        })
        try:
            response = urlopen(request)
        except HTTPError as e:
            raise RequestError("recognition request failed: {0}".format(getattr(e, "reason", "status {0}".format(e.code)))) # use getattr to be compatible with Python 2.6
        except URLError as e:
            raise RequestError("recognition connection failed: {0}".format(e.reason))
        response_text = response.read().decode("utf-8")
        result = json.loads(response_text)

        # return results
        if show_all: return result
        if "header" not in result or "lexical" not in result["header"]: raise UnknownValueError()
        return result["header"]["lexical"]


    def recognize_google(self,audio_data, key = None, language = "en-US", show_all = False):
        """
        Performs speech recognition on ``audio_data`` (an ``AudioData`` instance), using the Google Speech Recognition API.
        The Google Speech Recognition API key is specified by ``key``. If not specified, it uses a generic key that works out of the box. This should generally be used for personal or testing purposes only, as it **may be revoked by Google at any time**.
        To obtain your own API key, simply following the steps on the `API Keys <http://www.chromium.org/developers/how-tos/api-keys>`__ page at the Chromium Developers site. In the Google Developers Console, Google Speech Recognition is listed as "Speech API".
        The recognition language is determined by ``language``, an RFC5646 language tag like ``"en-US"`` (US English) or ``"fr-FR"`` (International French), defaulting to US English. A list of supported language values can be found in this `StackOverflow answer <http://stackoverflow.com/a/14302134>`__.
        Returns the most likely transcription if ``show_all`` is false (the default). Otherwise, returns the raw API response as a JSON dictionary.
        Raises a ``speech_recognition.UnknownValueError`` exception if the speech is unintelligible. Raises a ``speech_recognition.RequestError`` exception if the speech recognition operation failed, if the key isn't valid, or if there is no internet connection.
        """

        try: # attempt to use the Python 2 modules
            from urllib import urlencode
            from urllib2 import Request, urlopen, URLError, HTTPError
        except ImportError: # use the Python 3 modules
            from urllib.parse import urlencode
            from urllib.request import Request, urlopen
            from urllib.error import URLError, HTTPError


        assert isinstance(audio_data, AudioData), "`audio_data` must be audio data"
        assert key is None or isinstance(key, str), "`key` must be `None` or a string"
        assert isinstance(language, str), "`language` must be a string"

        flac_data = audio_data.get_wav_data(
            convert_rate = 16000, # audio samples must be at least 8 kHz
            convert_width = 2 # audio samples must be 16-bit
        )
        if key is None: key = "AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw"
        url = "http://www.google.com/speech-api/v2/recognize?{0}".format(urlencode({
            "client": "chromium",
            "lang": language,
            "key": key,
        }))
        request = Request(url, data = flac_data, headers = {"Content-Type": "audio/l16; rate=16000"})

        # obtain audio transcription results
        try:
            response = urlopen(request)
        except HTTPError as e:
            raise RequestError("recognition request failed: {0}".format(getattr(e, "reason", "status {0}".format(e.code)))) # use getattr to be compatible with Python 2.6
        except URLError as e:
            raise RequestError("recognition connection failed: {0}".format(e.reason))
        response_text = response.read().decode("utf-8")
        #.

        # ignore any blank blocks
        actual_result = []
        for line in response_text.split("\n"):
            if not line: continue
            result = json.loads(line)["result"]
            if len(result) != 0:
                actual_result = result[0]
                break

        # return results
        if show_all: return actual_result
        if "alternative" not in actual_result: raise UnknownValueError()
        for entry in actual_result["alternative"]:
            if "transcript" in entry:
                return entry["transcript"]
        raise UnknownValueError() # no transcriptions available

    def recognize_wit(self, audio_data, key, show_all = False):
        """
        Performs speech recognition on ``audio_data`` (an ``AudioData`` instance), using the Wit.ai API.
        The Wit.ai API key is specified by ``key``. Unfortunately, these are not available without `signing up for an account <https://wit.ai/>`__ and creating an app. You will need to add at least one intent to the app before you can see the API key, though the actual intent settings don't matter.
        To get the API key for a Wit.ai app, go to the app's overview page, go to the section titled "Make an API request", and look for something along the lines of ``Authorization: Bearer XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX``; ``XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`` is the API key. Wit.ai API keys are 32-character uppercase alphanumeric strings.
        The recognition language is configured in the Wit.ai app settings.
        Returns the most likely transcription if ``show_all`` is false (the default). Otherwise, returns the `raw API response <https://wit.ai/docs/http/20141022#get-intent-via-text-link>`__ as a JSON dictionary.
        Raises a ``speech_recognition.UnknownValueError`` exception if the speech is unintelligible. Raises a ``speech_recognition.RequestError`` exception if the speech recognition operation failed, if the key isn't valid, or if there is no internet connection.
        """
        try: # attempt to use the Python 2 modules
            from urllib import urlencode
            from urllib2 import Request, urlopen, URLError, HTTPError
        except ImportError: # use the Python 3 modules
            from urllib.parse import urlencode
            from urllib.request import Request, urlopen
            from urllib.error import URLError, HTTPError
        assert isinstance(audio_data, AudioData), "Data must be audio data"
        assert isinstance(key, str), "`key` must be a string"

        wav_data = audio_data.get_wav_data(
            convert_rate = None if audio_data.sample_rate >= 8000 else 8000, # audio samples must be at least 8 kHz
            convert_width = 2 # audio samples should be 16-bit
        )
        url = "https://api.wit.ai/speech?v=20141022"
        request = Request(url, data = wav_data, headers = {"Authorization": "Bearer {0}".format(key), "Content-Type": "audio/wav"})
        try:
            response = urlopen(request)
        except HTTPError as e:
            raise RequestError("recognition request failed: {0}".format(getattr(e, "reason", "status {0}".format(e.code)))) # use getattr to be compatible with Python 2.6
        except URLError as e:
            raise RequestError("recognition connection failed: {0}".format(e.reason))
        response_text = response.read().decode("utf-8")
        result = json.loads(response_text)

        # return results
        if show_all: return result
        if "_text" not in result or result["_text"] is None: raise UnknownValueError()
        return result["_text"]


def shutil_which(pgm):
    """Python 2 backport of ``shutil.which()`` from Python 3"""
    path = os.getenv('PATH')
    for p in path.split(os.path.pathsep):
        p = os.path.join(p, pgm)
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p

    
def gettoken(uid):
    red = redis.from_url(redis_url)
    token = red.get(uid+"-access_token")
    refresh = red.get(uid+"-refresh_token")
    if token:
        return token
    elif refresh:
        #good refresh token
        try:
            payload = {"client_id" : Client_ID, "client_secret" : Client_Secret, "refresh_token" : refresh, "grant_type" : "refresh_token", }
            url = "https://api.amazon.com/auth/o2/token"
            r = requests.post(url, data = payload)
            resp = json.loads(r.text)
            red.set(uid+"-access_token", resp['access_token'])
            red.expire(uid+"-access_token", 3600)
            return resp['access_token']
        #bad refresh token
        except:
            return False
    else:
        return False

#function version of getting Alexa's response in text
@timeout_dec(20)
def getAlexa(msg, mid, is_audio=False):
        print("getting post...")#
        # uid = tornado.escape.xhtml_escape(self.current_user)
        token = gettoken(mid)
        #token=""
        if (token == False):
            red = redis.from_url(redis_url)
            red.delete(mid+"-refresh_token")
            return "Sorry, it looks like you didn't log in to Amazon correctly. Try again here https://amazonalexabot.herokuapp.com/start and come back with your code."
        else:
            print("getting argument...")
            if not is_audio:  # received text
                phrase=msg
                print(phrase)
                #http://translate.google.com/translate_tts?ie=UTF-8&total=1&idx=0&textlen=32&client=tw-ob&q=hello&tl=En-us
                audio = requests.get('https://api.voicerss.org/', verify=False, params={'key': VoiceRSS_Token, 'src': phrase, 'hl': 'en-us', 'c': 'WAV', 'f': '16khz_16bit_mono'})
                rxfile = audio.content
                tf = tempfile.NamedTemporaryFile(suffix=".wav")
                tf.write(rxfile)
                _input = AudioSegment.from_wav(tf.name)
                tf.close()
            else:  # received audio
                rxfile = urllib2.urlopen(msg).read()
                print "got audio from facebook at " + msg
                # convert mp4 to wav
                tf = tempfile.NamedTemporaryFile(suffix=".mp4")
                tf.write(rxfile)
                _input = AudioSegment.from_file(tf.name, format="mp4")
                tf.close()
                print "got AudioSegment from mp4"
           

            tf = tempfile.NamedTemporaryFile(suffix=".wav")
            output = _input.set_channels(1).set_frame_rate(16000)
            f = output.export(tf.name, format="wav")
            url = 'https://access-alexa-na.amazon.com/v1/avs/speechrecognizer/recognize'
            headers = {'Authorization' : 'Bearer %s' % token}
            d = {
                "messageHeader": {
                    "deviceContext": [
                        {
                            "name": "playbackState",
                            "namespace": "AudioPlayer",
                            "payload": {
                                "streamId": "",
                                "offsetInMilliseconds": "0",
                                "playerActivity": "IDLE"
                            }
                        }
                    ]
                },
                "messageBody": {
                    "profile": "alexa-close-talk",
                    "locale": "en-us",
                    "format": "audio/L16; rate=16000; channels=1"
                }
            }
            files = [
                ('file', ('request', json.dumps(d), 'application/json; charset=UTF-8')),
                ('file', ('audio', tf, 'audio/L16; rate=16000; channels=1'))
            ]   
            r = requests.post(url, headers=headers, files=files)
            tf.close()
            for v in r.headers['content-type'].split(";"):
                if re.match('.*boundary.*', v):
                    boundary =  v.split("=")[1]
            
            if "boundary" in locals():
                data = r.content.split(boundary)
                for d in data:
                    if (len(d) >= 1024):
                        audio = d.split('\r\n\r\n')[1].rstrip('--')
            else:
                audio = r.content.split('\r\n\r\n')[1].rstrip('--')

            tf2 = tempfile.NamedTemporaryFile(suffix=".mp3")
            tf2.write(audio)
            _input2 = AudioSegment.from_mp3(tf2.name)
            tf2.close()

            #convert mp3 file to wav
            tf3 = tempfile.NamedTemporaryFile(suffix=".wav")
            #output2=_input2.export(tf3.name, format="wav",bitrate="16k",parameters=["-ac", "1", "-acodec", "pcm_s16le"])
            output2=_input2.export(tf3.name, format="wav")
 
            r = Recognizer()
            with AudioFile(tf3) as source:
                audio2 = r.record(source) # read the entire audio file

           # # recognize speech using Microsoft Bing Voice Recognition
           #  BING_KEY = "578545f1fb3940fb99151cfd79b476b1" # Microsoft Bing Voice Recognition API keys 32-character lowercase hexadecimal strings
           #  try:
           #      print("Microsoft Bing Voice Recognition thinks you said " + r.recognize_bing(audio2, key=BING_KEY))
           #  except UnknownValueError:
           #      print("Microsoft Bing Voice Recognition could not understand audio")
           #  except RequestError as e:
           #      print("Could not request results from Microsoft Bing Voice Recognition service; {0}".format(e))

            # recognize speech using Google Speech Recognition
            try:
                # for testing purposes, we're just using the default API key
                # to use another API key, use `r.recognize_google(audio, key="GOOGLE_SPEECH_RECOGNITION_API_KEY")`
                # instead of `r.recognize_google(audio)`
                transcription=r.recognize_google(audio2, key=Google_Speech_Token)
                print("Google Speech Recognition thinks you said " + transcription)
            except (UnknownValueError, RequestError):
                 # recognize speech using Wit.ai
                print(token)
                WIT_AI_KEY = Wit_Token # Wit.ai keys are 32-character uppercase alphanumeric strings
                try:
                    transcription=r.recognize_wit(audio2, key=WIT_AI_KEY)
                    print("Wit.ai thinks you said " + transcription)
                except UnknownValueError:
                    print("Wit.ai could not understand audio")
                except RequestError as e:
                    print("Could not request results from Wit.ai service; {0}".format(e))

                print("Google Speech Recognition could not understand audio")

            return transcription

    
class BaseHandler(tornado.web.RequestHandler):
    def get_current_user(self):
        return self.get_cookie("user")


class MainHandler(BaseHandler):
    # @tornado.web.authenticated
    @tornado.web.asynchronous
    def get(self):
        self.render("static/tokengenerator.html", token=self.get_argument("refreshtoken"))


class StartAuthHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(self):
        mid=self.get_argument("mid", default=None, strip=False)
        scope="alexa_all"
        sd = json.dumps({
            "alexa:all": {
                "productID": Product_ID,
                "productInstanceAttributes": {
                    "deviceSerialNumber": "1"
                }
            }
        })
        url = "https://www.amazon.com/ap/oa"
        path = "https" + "://" + self.request.host 
        if mid != None:
            self.set_cookie("user", mid)
        callback = path + "/code"
        payload = {"client_id" : Client_ID, "scope" : "alexa:all", "scope_data" : sd, "response_type" : "code", "redirect_uri" : callback }
        req = Request('GET', url, params=payload)
        p = req.prepare()
        self.redirect(p.url)


class CodeAuthHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(self):
        code=self.get_argument("code")
        mid=self.get_cookie("user")
        path = "https" + "://" + self.request.host 
        callback = path+"/code"
        payload = {"client_id" : Client_ID, "client_secret" : Client_Secret, "code" : code, "grant_type" : "authorization_code", "redirect_uri" : callback }
        url = "https://api.amazon.com/auth/o2/token"
        r = requests.post(url, data = payload)
        red = redis.from_url(redis_url)
        resp = json.loads(r.text)
        if mid != None:
            print("fetched MID: ",mid)
            red.set(mid+"-access_token", resp['access_token'])
            red.expire(mid+"-access_token", 3600)
            red.set(mid+"-refresh_token", resp['refresh_token'])
            self.render("static/return.html")
            bot.send_text_message(mid, "Great, you're logged in. Start talking to Alexa!")
        else:
            self.redirect("/?refreshtoken="+resp['refresh_token'])                  

class LogoutHandler(BaseHandler):
    @tornado.web.authenticated
    @tornado.web.asynchronous
    def get(self):
        uid = tornado.escape.xhtml_escape(self.current_user)
        red = redis.from_url(redis_url)
        red.delete(uid+"-access_token")
        red.delete(uid+"-refresh_token")
        self.clear_cookie("user")
        self.set_header('Content-Type', 'text/plain')
        self.write("Logged Out, Goodbye")
        self.finish()

class MessageHandler(BaseHandler):
    @tornado.web.asynchronous
    def get(self):
        if (self.get_argument("hub.verify_token", default=None, strip=False) == "my_voice_is_my_password_verify_me"):
            self.set_header('Content-Type', 'text/plain')
            self.write(self.get_argument("hub.challenge", default=None, strip=False))
            self.finish()
    
    def post(self):
        output = tornado.escape.json_decode(self.request.body) 
        print("OUTPUT: ",output)
        try:
            event = output['entry'][0]['messaging']
            for x in event:
                recipient_id = x['sender']['id']
                if "postback" in x and "payload" in x['postback']:
                    payload = x['postback']['payload']
                    if payload=="AUTH":
                        print("Generating login link...")
                        link='https://amazonalexabot.herokuapp.com/start?mid='+recipient_id
                        messageData = {"attachment": {"type": "template","payload": {"template_type": "generic","elements": [{"title": "Login to Amazon","buttons": [{"type": "web_url","url": link,"title": "Login"}]}]}}}
                        payload = {"recipient": {"id": recipient_id}, "message": messageData}
                        r = requests.post("https://graph.facebook.com/v2.6/me/messages?access_token="+TOKEN, json=payload)
                        print(r.text)
                        print("Made post request")
                elif "message" in x and "sticker_id" in x["message"]:
                    print("received sticker")
                    bot.send_text_message(recipient_id, "(y)")
                elif "message" in x and "attachments" in x["message"] and x["message"]["attachments"][0]["type"] == "audio":
                    print "received audio message"
                    url = x["message"]["attachments"][0]["payload"]["url"]
                    print("Getting Alexa's response from AudioHandler")
                    # alexaresponse = requests.get('https://amazonalexabot.herokuapp.com/audio', params={'text': message})
                    alexaresponse = getAlexa(url,recipient_id, True)
                    print("Alexa's response: ", alexaresponse)
                    # bot.send_text_message(recipient_id, alexaresponse.text)
                    if len(alexaresponse) > 320:
                        alexaresponse = alexaresponse[:317] + "..."
                    bot.send_text_message(recipient_id, alexaresponse)
                elif "message" in x and "text" in x['message']:
                    message = x['message']['text']
                    print("The message:", message)
                    if message.lower() in {"hi", "hello", "hi alexa", "hello alexa","hi there","hey alexa","hey", "hello there"}:
                        bot.send_text_message(recipient_id, "hi there")
                    elif message.lower() in {"help", "help me"}:
                        bot.send_text_message(recipient_id, "Type anything you would say to Amazon's Alexa assistant and receive her response. For more help with what you can say, check out the Things to Try section of the Alexa app.")
                    else:
                        red = redis.from_url(redis_url)
                        if not red.exists(recipient_id+"-refresh_token"):
                            print("Received refresh token")
                            red.set(recipient_id+"-refresh_token", message)
                            testing=gettoken(recipient_id)
                            if(testing==False):
                                red.delete(recipient_id+"-refresh_token")
                                link='https://amazonalexabot.herokuapp.com/start?mid='+recipient_id
                                messageData = {"attachment": {"type": "template","payload": {"template_type": "generic","elements": [{"title": "You are not logged in properly.","buttons": [{"type": "web_url","url": link,"title": "Login"}]}]}}}
                                payload = {"recipient": {"id": recipient_id}, "message": messageData}
                                r = requests.post("https://graph.facebook.com/v2.6/me/messages?access_token="+TOKEN, json=payload)
                            else:
                                bot.send_text_message(recipient_id, "Great, you're logged in. Start talking to Alexa!")
                          
                        else:
                            print("Getting Alexa's response from AudioHandler. Message was: "+message)
                            # alexaresponse = requests.get('https://amazonalexabot.herokuapp.com/audio', params={'text': message})
                            alexaresponse = getAlexa(message,recipient_id)
                            print("Alexa's response: ", alexaresponse)
                            # bot.send_text_message(recipient_id, alexaresponse.text)
                            if len(alexaresponse) > 320:
                                alexaresponse = alexaresponse[:317] + "..."
                            bot.send_text_message(recipient_id, alexaresponse)
                else:
                    pass
        except TimeoutError:
            print(traceback.format_exc())
            bot.send_text_message(recipient_id, "Request took too long.")
        except Exception,err:
            print("Couldn't understand: ", traceback.format_exc())
            bot.send_text_message(recipient_id, "Sorry, something went wrong.")
        self.set_status(200)
        self.finish()

    def write_error(self, status_code, **kwargs):
        self.write("Gosh darnit, user! You caused a %d error." % status_code)


#REST API version of getAlexa, pass in token and text, get text back
class AudioHandler(BaseHandler):
    # @tornado.web.authenticated
    @tornado.web.asynchronous
    def get(self):
        print("getting post...")#
        # uid = tornado.escape.xhtml_escape(self.current_user)

        token=self.get_argument("token") #get argument later

        print("getting argument...")
        phrase=self.get_argument("text")
        print(phrase)
        #http://translate.google.com/translate_tts?ie=UTF-8&total=1&idx=0&textlen=32&client=tw-ob&q=hello&tl=En-us
        audio = requests.get('https://api.voicerss.org/', params={'key': VoiceRSS_Token, 'src': phrase, 'hl': 'en-us', 'c': 'WAV', 'f': '16khz_16bit_mono'})
        rxfile = audio.content

        tf = tempfile.NamedTemporaryFile(suffix=".wav")
        tf.write(rxfile)
        _input = AudioSegment.from_wav(tf.name)
        tf.close()

        tf = tempfile.NamedTemporaryFile(suffix=".wav")
        output = _input.set_channels(1).set_frame_rate(16000)
        f = output.export(tf.name, format="wav")
        url = 'https://access-alexa-na.amazon.com/v1/avs/speechrecognizer/recognize'
        headers = {'Authorization' : 'Bearer %s' % token}
        d = {
            "messageHeader": {
                "deviceContext": [
                    {
                        "name": "playbackState",
                        "namespace": "AudioPlayer",
                        "payload": {
                            "streamId": "",
                            "offsetInMilliseconds": "0",
                            "playerActivity": "IDLE"
                        }
                    }
                ]
            },
            "messageBody": {
                "profile": "alexa-close-talk",
                "locale": "en-us",
                "format": "audio/L16; rate=16000; channels=1"
            }
        }
        files = [
            ('file', ('request', json.dumps(d), 'application/json; charset=UTF-8')),
            ('file', ('audio', tf, 'audio/L16; rate=16000; channels=1'))
        ]   
        r = requests.post(url, headers=headers, files=files)
        tf.close()
        for v in r.headers['content-type'].split(";"):
            if re.match('.*boundary.*', v):
                boundary =  v.split("=")[1]

        data = r.content.split(boundary)
        for d in data:
            if (len(d) >= 1024):
               audio = d.split('\r\n\r\n')[1].rstrip('--')

        tf2 = tempfile.NamedTemporaryFile(suffix=".mp3")
        tf2.write(audio)
        _input2 = AudioSegment.from_mp3(tf2.name) 
        tf2.close()

        #convert mp3 file to wav
        tf3 = tempfile.NamedTemporaryFile(suffix=".wav")
        output2=_input2.export(tf3.name, format="wav")

        r = Recognizer()
        with AudioFile(tf3) as source:
            audio2 = r.record(source) # read the entire audio file

        # recognize speech using Microsoft Bing Voice Recognition
        BING_KEY = "ca19922330ba4b87819b93f35d4fea68" # Microsoft Bing Voice Recognition API keys 32-character lowercase hexadecimal strings
        try:
            print("Microsoft Bing Voice Recognition thinks you said " + r.recognize_bing(audio2, key=BING_KEY))
        except UnknownValueError:
            print("Microsoft Bing Voice Recognition could not understand audio")
        except RequestError as e:
            print("Could not request results from Microsoft Bing Voice Recognition service; {0}".format(e))

        # recognize speech using Google Speech Recognition
        try:
            # for testing purposes, we're just using the default API key.
            # to use another API key, use `r.recognize_google(audio, key="GOOGLE_SPEECH_RECOGNITION_API_KEY")`
            # instead of `r.recognize_google(audio)`
            transcription=r.recognize_google(audio2, key=Google_Speech_Token)
            print("Google Speech Recognition thinks you said " + transcriptionG)
        except:
            # recognize speech using Wit.ai
            print(token)
            WIT_AI_KEY = Wit_Token # Wit.ai keys are 32-character uppercase alphanumeric strings
            try:
                transcription=r.recognize_wit(audio2, key=WIT_AI_KEY)
                print("Wit.ai thinks you said " + transcription)
            except UnknownValueError:
                print("Wit.ai could not understand audio")
            except RequestError as e:
                print("Could not request results from Wit.ai service; {0}".format(e))

        #except UnknownValueError:
        #    transcriptionG=transcriptionW
        #    print("Google Speech Recognition could not understand audio")
        #except RequestError as e:
        #    transcriptionG=transcriptionW
        #    print("Could not request results from Google Speech Recognition service; {0}".format(e))


        self.set_header('Content-Type', 'text/plain')
        self.write(transcription)
        self.finish()


#REST API version of getAlexa, pass in token and text, get text back
class AudioHandler(BaseHandler):
    # @tornado.web.authenticated
    @tornado.web.asynchronous
    def get(self):
        print("getting post...")#
        # uid = tornado.escape.xhtml_escape(self.current_user)
        # token = gettoken(uid)
        token="" #get argument later
        if token == False:
            self.set_status(403)
        else:
            print("geting argument...")
            phrase=self.get_argument("text", default=None, strip=False)
            print(phrase)

            audio = requests.get('http://www.voicerss.org/controls/speech.ashx', params={'src': phrase, 'hl': 'en-us', 'c': 'WAV', 'f': '16khz_16bit_mono'})
            rxfile = audio.content

            tf = tempfile.NamedTemporaryFile(suffix=".wav")
            tf.write(rxfile)
            _input = AudioSegment.from_wav(tf.name)
            tf.close()

            tf = tempfile.NamedTemporaryFile(suffix=".wav")
            output = _input.set_channels(1).set_frame_rate(16000)
            f = output.export(tf.name, format="wav")
            url = 'https://access-alexa-na.amazon.com/v1/avs/speechrecognizer/recognize'
            headers = {'Authorization' : 'Bearer %s' % token}
            d = {
                "messageHeader": {
                    "deviceContext": [
                        {
                            "name": "playbackState",
                            "namespace": "AudioPlayer",
                            "payload": {
                                "streamId": "",
                                "offsetInMilliseconds": "0",
                                "playerActivity": "IDLE"
                            }
                        }
                    ]
                },
                "messageBody": {
                    "profile": "alexa-close-talk",
                    "locale": "en-us",
                    "format": "audio/L16; rate=16000; channels=1"
                }
            }
            files = [
                ('file', ('request', json.dumps(d), 'application/json; charset=UTF-8')),
                ('file', ('audio', tf, 'audio/L16; rate=16000; channels=1'))
            ]   
            r = requests.post(url, headers=headers, files=files)
            tf.close()
            for v in r.headers['content-type'].split(";"):
                if re.match('.*boundary.*', v):
                    boundary =  v.split("=")[1]
            data = r.content.split(boundary)
            for d in data:
                if (len(d) >= 1024):
                   audio = d.split('\r\n\r\n')[1].rstrip('--')

            tf2 = tempfile.NamedTemporaryFile(suffix=".mp3")
            tf2.write(audio)
            _input2 = AudioSegment.from_mp3(tf2.name)
            tf2.close()

            tf3 = tempfile.NamedTemporaryFile(suffix=".wav")
            output2=_input2.export(tf3.name, format="wav")

            r = sr.Recognizer()
            with sr.AudioFile(tf3) as source:
                audio2 = r.record(source) # read the entire audio file

            # recognize speech using Wit.ai
            print(token)
            WIT_AI_KEY = Wit_Token # Wit.ai keys are 32-character uppercase alphanumeric strings
            try:
                transcription=r.recognize_wit(audio2, key=WIT_AI_KEY)
                print("Wit.ai thinks you said " + transcription)
            except sr.UnknownValueError:
                print("Wit.ai could not understand audio")
            except sr.RequestError as e:
                print("Could not request results from Wit.ai service; {0}".format(e))

            self.set_header('Content-Type', 'text/plain')
            self.write(transcription)
            self.finish()


def main():
    settings = {
        "cookie_secret": "parisPOLANDbroadFENCEcornWOULD",
        # url
    }
    static_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    application = tornado.web.Application([(r"/", MainHandler),
                                            (r"/start", StartAuthHandler),
                                            (r"/code", CodeAuthHandler),
                                            (r"/logout", LogoutHandler),
                                            (r"/audio", AudioHandler),
                                            (r"/webhook", MessageHandler),
                                            (r'/(favicon.ico)', tornado.web.StaticFileHandler,{'path': static_path}),
                                            (r'/static/(.*)', tornado.web.StaticFileHandler, {'path': static_path}),
                                            ], **settings)
    http_server = tornado.httpserver.HTTPServer(application)
    port = int(os.environ.get("PORT", 5000))
    http_server.listen(port)
    tornado.ioloop.IOLoop.instance().start()

if __name__ == "__main__":
    main()

