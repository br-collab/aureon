import { useState, useEffect, useRef, useCallback } from "react";

// Ordered preference list — picked in this order if available
// macOS / iOS Safari expose Samantha, Ava, Allison, Susan, Victoria, Karen (US English female voices)
// Chrome exposes "Google US English" as its default female US voice
const FEMALE_US_PREFERENCES = [
  "Samantha",
  "Ava (Premium)",
  "Ava (Enhanced)",
  "Ava",
  "Allison",
  "Susan",
  "Victoria",
  "Kathy",
  "Google US English",
];

const FEMALE_NAME_HINTS = /samantha|ava|allison|karen|susan|victoria|zoe|kate|kathy|nicky|female/i;

const pickVoice = (voices) => {
  const enUS = voices.filter(v => v.lang === "en-US" || v.lang === "en_US");
  for (const name of FEMALE_US_PREFERENCES) {
    const exact = enUS.find(v => v.name === name);
    if (exact) return exact;
    const prefix = enUS.find(v => v.name.startsWith(name));
    if (prefix) return prefix;
  }
  const heuristic = enUS.find(v => FEMALE_NAME_HINTS.test(v.name));
  return heuristic || enUS[0] || voices[0] || null;
};

const stripForSpeech = (text) =>
  text
    .replace(/\[AUDIT:[\s\S]*?\]/g, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/\*(.*?)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^[-*]\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();

export function useVoice(enabledDefault = true) {
  const synth = typeof window !== "undefined" ? window.speechSynthesis : null;
  const supported = Boolean(synth);

  const [enabled, setEnabled] = useState(supported && enabledDefault);
  const [voice, setVoice] = useState(null);
  const voiceRef = useRef(null);
  const enabledRef = useRef(enabled);

  useEffect(() => { enabledRef.current = enabled; }, [enabled]);

  useEffect(() => {
    if (!synth) return;
    const load = () => {
      const all = synth.getVoices();
      if (all.length === 0) return;
      const picked = pickVoice(all);
      voiceRef.current = picked;
      setVoice(picked);
    };
    load();
    synth.addEventListener?.("voiceschanged", load);
    return () => {
      synth.removeEventListener?.("voiceschanged", load);
      synth.cancel();
    };
  }, [synth]);

  const speak = useCallback((text) => {
    if (!synth || !enabledRef.current || !text) return;
    const clean = stripForSpeech(text);
    if (!clean) return;
    synth.cancel();
    const utter = new SpeechSynthesisUtterance(clean);
    if (voiceRef.current) utter.voice = voiceRef.current;
    utter.lang = voiceRef.current?.lang || "en-US";
    utter.rate = 1.0;
    utter.pitch = 1.0;
    utter.volume = 1.0;
    synth.speak(utter);
  }, [synth]);

  const cancel = useCallback(() => {
    if (synth) synth.cancel();
  }, [synth]);

  const toggle = useCallback(() => {
    setEnabled(prev => {
      if (prev && synth) synth.cancel();
      return !prev;
    });
  }, [synth]);

  return { enabled, supported, voice, speak, cancel, toggle };
}
