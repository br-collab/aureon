import { useState, useEffect, useRef, useCallback } from "react";

const getRecognitionClass = () => {
  if (typeof window === "undefined") return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
};

// Web Speech API transcribes spoken digits as words ("zero seven three zero two").
// For KYC fields (zips, SSNs, passport numbers, phone numbers, dates) we want the
// digit form. We (1) replace digit-words with digits, then (2) collapse runs of
// 2+ standalone digits into one continuous number. Lone digits stay lone
// ("apartment 2 Jersey" → "apartment 2 Jersey") so we don't mangle real prose.
const DIGIT_WORDS = {
  zero: "0", oh: "0", one: "1", two: "2", three: "3", four: "4",
  five: "5", six: "6", seven: "7", eight: "8", nine: "9",
};
const normalizeDigits = (text) => {
  if (!text) return text;
  const worded = text.replace(
    /\b(zero|oh|one|two|three|four|five|six|seven|eight|nine)\b/gi,
    (w) => DIGIT_WORDS[w.toLowerCase()],
  );
  return worded.replace(/\b\d\b(?:\s+\b\d\b)+/g, (run) => run.replace(/\s+/g, ""));
};

// continuous=true + interimResults=true: the user controls start/stop explicitly.
// They dictate, we show live transcript in the input field, they click mic again
// to stop, then review + correct + Submit. No auto-send — matches the
// "confirm what was heard" compliance gate for KYC data accuracy.
export function useSpeechRecognition({ onTranscript, lang = "en-US", normalize = true } = {}) {
  const RecognitionClass = getRecognitionClass();
  const supported = Boolean(RecognitionClass);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState(null);
  const recognitionRef = useRef(null);
  const onTranscriptRef = useRef(onTranscript);
  const baseTextRef = useRef("");

  useEffect(() => { onTranscriptRef.current = onTranscript; }, [onTranscript]);

  useEffect(() => {
    if (!supported) return;
    const rec = new RecognitionClass();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = lang;

    rec.onresult = (event) => {
      let interim = "";
      let final = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript;
        if (event.results[i].isFinal) final += t;
        else interim += t;
      }
      const rawCombined = [baseTextRef.current, final, interim]
        .filter(Boolean)
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();
      const combined = normalize ? normalizeDigits(rawCombined) : rawCombined;
      if (final) {
        const nextBase = [baseTextRef.current, final].filter(Boolean).join(" ").trim();
        baseTextRef.current = normalize ? normalizeDigits(nextBase) : nextBase;
      }
      onTranscriptRef.current?.(combined, Boolean(final));
    };

    rec.onerror = (event) => {
      setError(event.error || "recognition_error");
      setListening(false);
    };

    rec.onend = () => {
      setListening(false);
    };

    recognitionRef.current = rec;
    return () => {
      try { rec.abort(); } catch { /* noop */ }
      recognitionRef.current = null;
    };
  }, [supported, RecognitionClass, lang]);

  const start = useCallback((seedText = "") => {
    if (!recognitionRef.current || listening) return;
    setError(null);
    baseTextRef.current = seedText.trim();
    try {
      recognitionRef.current.start();
      setListening(true);
    } catch (e) {
      setError(String(e));
    }
  }, [listening]);

  const stop = useCallback(() => {
    if (!recognitionRef.current || !listening) return;
    try { recognitionRef.current.stop(); } catch { /* noop */ }
  }, [listening]);

  const toggle = useCallback((seedText = "") => {
    if (listening) {
      try { recognitionRef.current?.stop(); } catch { /* noop */ }
    } else {
      if (!recognitionRef.current) return;
      setError(null);
      baseTextRef.current = seedText.trim();
      try {
        recognitionRef.current.start();
        setListening(true);
      } catch (e) {
        setError(String(e));
      }
    }
  }, [listening]);

  return { supported, listening, error, start, stop, toggle };
}
