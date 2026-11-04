"""Language label for intake text: en, hi (Devanagari) or mixed (Hinglish, or two scripts)."""

from typing import Literal

from sahyog.safety.text import DEVANAGARI, LATIN, normalise, tokens

Language = Literal["en", "hi", "mixed"]

# Romanised Hindi words that are not also common English words ("to", "me", "hi" are left out)
HINGLISH = frozenset(
    """
    hai hain ho hoon hun tha thi raha rahi rahe hua hui nahi nahin mein mujhe mera meri mere
    aur bahut bohot kya kyun kab se ka ki ke ko par pe wala wali dard bukhar khansi ulti
    chakkar kamzori jalan saans sans pet sir kaan aankh daant gala gardan haath pair kamar
    dawai dawa ji abhi kal aaj din raat subah shaam baar thoda zyada jyada lagta
    lagti lag gaya gayi gaye kar karna karta karti chahta chahti hoon de sunai dikhai khana
    peshab potty khoon pasina paseena seene seena chhati behosh daura mann jeene khud khatam
    dakaar khatti taklif takleef naam le lo liya diya aaya aayi aayega aayenge bhi saath
    """.split()
)


def detect(text: str) -> Language:
    norm = normalise(text)
    devanagari = len(DEVANAGARI.findall(norm))
    latin = len(LATIN.findall(norm))
    if devanagari and latin:
        return "mixed"
    if devanagari:
        return "hi"
    words = tokens(norm)
    hinglish = sum(w in HINGLISH for w in words)
    if hinglish >= 2 or (words and hinglish / len(words) >= 0.2):
        return "mixed"
    return "en"
