"""Fixed patient messages for W1, never model-written. Need clinician review before real use."""

from datetime import datetime
from zoneinfo import ZoneInfo

MESSAGES: dict[str, dict[str, str]] = {
    "emergency": {
        "en": "This may be an emergency. Please go to the nearest emergency department now, or "
        "call 112 or 108 for an ambulance. Do not wait for an appointment. Our emergency desk has "
        "been told.",
        "hi": "यह आपात स्थिति हो सकती है। कृपया अभी नज़दीकी इमरजेंसी विभाग जाएं या एम्बुलेंस के लिए "
        "112 या 108 पर कॉल करें। अपॉइंटमेंट का इंतज़ार न करें। हमारे इमरजेंसी डेस्क को सूचना दे दी गई है।",
        "mixed": "Yeh emergency ho sakti hai. Kripya abhi nazdeeki emergency department jaayein, ya "
        "ambulance ke liye 112 ya 108 par call karein. Appointment ka intezaar na karein. Hamare "
        "emergency desk ko bata diya gaya hai.",
    },
    "self_harm": {
        "en": "You matter, and you don't have to face this alone. If you might act on these "
        "thoughts, please go to the nearest emergency department now or call 112. You can also "
        "talk to Tele-MANAS at 14416, any time. Our emergency desk has been told and will reach out.",
        "hi": "आप महत्वपूर्ण हैं और आपको इससे अकेले नहीं जूझना है। अगर आप इन विचारों पर अमल कर सकते हैं, तो "
        "कृपया अभी नज़दीकी इमरजेंसी विभाग जाएं या 112 पर कॉल करें। आप किसी भी समय टेली-मानस से 14416 पर बात "
        "कर सकते हैं। हमारे इमरजेंसी डेस्क को सूचना दे दी गई है और वे आपसे संपर्क करेंगे।",
        "mixed": "Aap important hain aur aapko yeh akele nahi jhelna hai. Agar aap in vichaaron par "
        "amal kar sakte hain, to kripya abhi nazdeeki emergency department jaayein ya 112 par call "
        "karein. Aap kabhi bhi Tele-MANAS se 14416 par baat kar sakte hain. Hamare emergency desk "
        "ko bata diya gaya hai aur woh aapse sampark karenge.",
    },
    "desk": {
        "en": "A member of our front desk will help you with this. If it gets worse or feels "
        "urgent, please go to the nearest emergency department or call 112.",
        "hi": "हमारे फ्रंट डेस्क का एक सदस्य इसमें आपकी मदद करेगा। अगर तकलीफ़ बढ़े या मामला ज़रूरी लगे, तो कृपया "
        "नज़दीकी इमरजेंसी विभाग जाएं या 112 पर कॉल करें।",
        "mixed": "Hamare front desk ka ek sadasya aapki madad karega. Agar takleef badhe ya urgent "
        "lage, to kripya nazdeeki emergency department jaayein ya 112 par call karein.",
    },
    "advice": {
        "en": "I can't suggest a diagnosis or a medicine; a doctor needs to do that. Our front desk "
        "will help you see the right doctor. If it gets worse or feels urgent, please go to the "
        "nearest emergency department or call 112.",
        "hi": "मैं बीमारी या दवा नहीं बता सकता; यह डॉक्टर ही बता सकते हैं। हमारा फ्रंट डेस्क सही डॉक्टर से मिलने "
        "में आपकी मदद करेगा। अगर तकलीफ़ बढ़े या मामला ज़रूरी लगे, तो कृपया नज़दीकी इमरजेंसी विभाग जाएं या 112 "
        "पर कॉल करें।",
        "mixed": "Main bimari ya dawai nahi bata sakta; yeh doctor hi bata sakte hain. Hamara front "
        "desk sahi doctor se milne mein aapki madad karega. Agar takleef badhe ya urgent lage, to "
        "kripya nazdeeki emergency department jaayein ya 112 par call karein.",
    },
    "block_taken": {
        "en": "That block has just filled up or is no longer available. Here are the next options.",
        "hi": "वह समय अभी भर गया या अब उपलब्ध नहीं है। ये अगले विकल्प हैं।",
        "mixed": "Woh block abhi bhar gaya ya ab available nahi hai. Yeh agle options hain.",
    },
    "already_booked": {
        "en": "You already have a token in that block. Please choose a different one.",
        "hi": "उस समय में आपका टोकन पहले से है। कृपया कोई दूसरा चुनें।",
        "mixed": "Us block mein aapka token pehle se hai. Kripya koi doosra chunein.",
    },
    "booked": {
        "en": "Booked: token {token} with {doctor}, {clinic}, between {start} and {end} on {day}. "
        "Please come at the start of the block; the exact time inside it can vary.",
        "hi": "बुकिंग हो गई: टोकन {token}, {doctor}, {clinic}, {day} को {start} से {end} के बीच। कृपया "
        "इस समय की शुरुआत में आएं; इसके अंदर सही समय बदल सकता है।",
        "mixed": "Booking ho gayi: token {token}, {doctor}, {clinic}, {day} ko {start} se {end} ke "
        "beech. Kripya block ki shuruaat mein aayein; iske andar exact time badal sakta hai.",
    },
}


def message(name: str, language: str, **values) -> str:
    text = MESSAGES[name].get(language) or MESSAGES[name]["en"]
    return text.format(**values) if values else text


def block_times(start: datetime | str, end: datetime | str, tz: str) -> dict[str, str]:
    zone = ZoneInfo(tz)
    s, e = (
        (datetime.fromisoformat(v) if isinstance(v, str) else v).astimezone(zone)
        for v in (start, end)
    )
    return {"start": f"{s:%H:%M}", "end": f"{e:%H:%M}", "day": f"{s:%d %b %Y}"}
