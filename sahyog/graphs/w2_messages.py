"""Fixed patient messages for W2, never model-written. Need clinician review before real use."""

MESSAGES: dict[str, dict[str, str]] = {
    "not_found": {
        "en": "I couldn't find that in your reports. A doctor or our front desk can help with it.",
        "hi": "मुझे यह आपकी रिपोर्ट में नहीं मिला। डॉक्टर या हमारा फ्रंट डेस्क इसमें मदद कर सकता है।",
        "mixed": "Mujhe yeh aapki report mein nahi mila. Doctor ya hamara front desk madad kar sakta hai.",
    },
    "refused": {
        "en": "I can read your reports back to you, but I can't tell you what they mean, name an "
        "illness or suggest a medicine or dose. A doctor needs to do that, and our front desk has "
        "been told.",
        "hi": "मैं आपकी रिपोर्ट पढ़कर बता सकता हूं, पर उनका मतलब, बीमारी या दवा और उसकी मात्रा नहीं बता सकता। यह "
        "डॉक्टर ही बता सकते हैं, और हमारे फ्रंट डेस्क को सूचना दे दी गई है।",
        "mixed": "Main aapki report padhkar bata sakta hoon, par uska matlab, bimari ya dawai aur "
        "uski matra nahi bata sakta. Yeh doctor hi bata sakte hain, aur hamare front desk ko bata "
        "diya gaya hai.",
    },
    "blocked": {
        "en": "I couldn't give you a reliable answer to that. Our front desk has been told and "
        "will help you.",
        "hi": "मैं इसका भरोसेमंद जवाब नहीं दे सका। हमारे फ्रंट डेस्क को सूचना दे दी गई है और वे आपकी मदद करेंगे।",
        "mixed": "Main iska bharosemand jawab nahi de saka. Hamare front desk ko bata diya gaya hai "
        "aur woh aapki madad karenge.",
    },
    "scan_warning": {
        "en": "This was read from a scanned page by a computer, and it can misread numbers. Please "
        "check it against the original report ({pages}).",
        "hi": "यह स्कैन किए गए पेज से कंप्यूटर ने पढ़ा है, और अंक गलत पढ़े जा सकते हैं। कृपया मूल रिपोर्ट से जांच "
        "लें ({pages})।",
        "mixed": "Yeh scan kiye gaye page se computer ne padha hai, aur number galat padhe ja sakte "
        "hain. Kripya original report se check kar lein ({pages}).",
    },
}
PAGE_WORD = {"en": "page", "hi": "पेज", "mixed": "page"}


def message(name: str, language: str, **values) -> str:
    text = MESSAGES[name].get(language) or MESSAGES[name]["en"]
    return text.format(**values) if values else text
