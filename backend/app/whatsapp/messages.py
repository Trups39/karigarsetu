"""Fixed WhatsApp messages in English, Marathi and Hindi.

Claude's own replies already follow the person's language. This file covers the messages the
code sends by itself: approval requests, confirmations, counter-offers, status updates, help text.

    t("retailer_confirmed", "Marathi", code="KS-1041", ...)

To change wording, edit the text here. Keep the {placeholders} the same in all three languages.
"""

import re
from datetime import date

LANGS = ("English", "Marathi", "Hindi")
DEFAULT = "English"


def norm(lang: str | None) -> str:
    """'marathi', 'mr', 'मराठी' -> 'Marathi'. Unknown -> English."""
    s = (lang or "").strip().lower()
    if s in ("marathi", "mr", "मराठी"):
        return "Marathi"
    if s in ("hindi", "hi", "हिंदी", "हिन्दी"):
        return "Hindi"
    return DEFAULT


MONTHS = {
    "Marathi": ["जानेवारी", "फेब्रुवारी", "मार्च", "एप्रिल", "मे", "जून", "जुलै", "ऑगस्ट", "सप्टेंबर", "ऑक्टोबर", "नोव्हेंबर", "डिसेंबर"],
    "Hindi": ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"],
}


def fmt_date(d: date | None, lang: str = DEFAULT) -> str:
    if not d:
        return "-"
    lang = norm(lang)
    if lang in MONTHS:
        return f"{d.day} {MONTHS[lang][d.month - 1]} {d.year}"
    return d.strftime("%d %b %Y")


SIZE_WORD = {"English": "size", "Marathi": "साइज", "Hindi": "साइज़"}


def sizes(lines: dict[int, int], lang: str = DEFAULT) -> str:
    word = SIZE_WORD[norm(lang)]
    return ", ".join(f"{word} {s}: {q}" for s, q in sorted(lines.items()))


STATUS = {
    "awaiting_maker": {
        "English": "waiting for the maker",
        "Marathi": "कारागिराच्या मंजुरीची वाट",
        "Hindi": "कारीगर की मंज़ूरी का इंतज़ार",
    },
    "counter_offered": {
        "English": "waiting for your reply",
        "Marathi": "तुमच्या उत्तराची वाट",
        "Hindi": "आपके जवाब का इंतज़ार",
    },
    "approved": {"English": "confirmed", "Marathi": "कन्फर्म", "Hindi": "कन्फ़र्म"},
    "in_production": {"English": "in production", "Marathi": "तयार होत आहे", "Hindi": "बन रहा है"},
    "ready": {"English": "ready to ship", "Marathi": "पाठवण्यासाठी तयार", "Hindi": "भेजने के लिए तैयार"},
    "delivered": {"English": "delivered", "Marathi": "पोहोचवली", "Hindi": "पहुंचा दिया गया"},
    "rejected": {"English": "cancelled", "Marathi": "रद्द", "Hindi": "रद्द"},
}


def status(value: str, lang: str = DEFAULT) -> str:
    return STATUS.get(value, {}).get(norm(lang), value)


TEXTS = {
    # ---- to the maker ----
    "maker_new_order": {
        "English": (
            "New bulk order {code}\nRetailer: {retailer}{city}\n{product}, {total} pairs ({lines})\n"
            "Ready: {ready} · To make: {to_make}\n"
            "Proposed delivery: {date} · {price}/pair · total {total_price}{request}\n\n{menu}"
        ),
        "Marathi": (
            "नवीन बल्क ऑर्डर {code}\nदुकान: {retailer}{city}\n{product}, {total} जोड्या ({lines})\n"
            "तयार: {ready} · बनवायच्या: {to_make}\n"
            "अंदाजे डिलिव्हरी: {date} · {price}/जोडी · एकूण {total_price}{request}\n\n{menu}"
        ),
        "Hindi": (
            "नया बल्क ऑर्डर {code}\nदुकान: {retailer}{city}\n{product}, {total} जोड़ी ({lines})\n"
            "तैयार: {ready} · बनानी हैं: {to_make}\n"
            "अनुमानित डिलीवरी: {date} · {price}/जोड़ी · कुल {total_price}{request}\n\n{menu}"
        ),
    },
    "maker_shop_request": {
        "English": "\nShop's request: {text}",
        "Marathi": "\nदुकानाची विनंती: {text}",
        "Hindi": "\nदुकान का अनुरोध: {text}",
    },
    "maker_shop_price": {
        "English": "\nShop's request: {price}/pair instead of {list_price} · new total {total_price}",
        "Marathi": "\nदुकानाची विनंती: {list_price} ऐवजी {price}/जोडी · नवीन एकूण {total_price}",
        "Hindi": "\nदुकान का अनुरोध: {list_price} की जगह {price}/जोड़ी · नया कुल {total_price}",
    },
    "maker_shop_date": {
        "English": "\nShop's request: delivery by {date}",
        "Marathi": "\nदुकानाची विनंती: डिलिव्हरी {date} पर्यंत",
        "Hindi": "\nदुकान का अनुरोध: डिलीवरी {date} तक",
    },
    "maker_shop_date_too_early": {
        "English": "\nShop's request: delivery by {date} (earliest possible is {earliest}; to offer a date, reply 3)",
        "Marathi": "\nदुकानाची विनंती: डिलिव्हरी {date} पर्यंत (सर्वात लवकर शक्य {earliest}; तारीख सुचवण्यासाठी 3 पाठवा)",
        "Hindi": "\nदुकान का अनुरोध: डिलीवरी {date} तक (सबसे जल्दी संभव {earliest}; तारीख सुझाने के लिए 3 भेजें)",
    },
    "maker_which_order": {
        "English": "You have {n} orders waiting: {codes}. Add the order code, e.g. {example}",
        "Marathi": "तुमच्याकडे {n} ऑर्डर मंजुरीसाठी आहेत: {codes}. ऑर्डर कोडसह पाठवा, उदा. {example}",
        "Hindi": "आपके पास {n} ऑर्डर मंज़ूरी के लिए हैं: {codes}. ऑर्डर कोड के साथ भेजें, जैसे {example}",
    },
    "maker_menu": {
        "English": "Reply 1 to approve, 2 to reject, 3 to propose a change.",
        "Marathi": "मंजुरीसाठी 1, नाकारण्यासाठी 2, बदल सुचवण्यासाठी 3 पाठवा.",
        "Hindi": "मंज़ूरी के लिए 1, मना करने के लिए 2, बदलाव के लिए 3 भेजें.",
    },
    "maker_menu_request": {
        "English": (
            "Reply 1 to approve with the shop's request ({summary}), 2 to reject, 3 to propose something else."
        ),
        "Marathi": "दुकानाची विनंती मान्य करून मंजुरीसाठी 1 ({summary}), नाकारण्यासाठी 2, वेगळा बदल सुचवण्यासाठी 3 पाठवा.",
        "Hindi": "दुकान का अनुरोध मानकर मंज़ूरी के लिए 1 ({summary}), मना करने के लिए 2, दूसरा बदल सुझाने के लिए 3 भेजें.",
    },
    "summary_price": {
        "English": "{price}/pair, total {total_price}",
        "Marathi": "{price}/जोडी, एकूण {total_price}",
        "Hindi": "{price}/जोड़ी, कुल {total_price}",
    },
    "summary_date": {"English": "delivery {date}", "Marathi": "डिलिव्हरी {date}", "Hindi": "डिलीवरी {date}"},
    "maker_approved": {
        "English": "Approved {code}: {price}/pair, total {total_price}. The retailer has been told. Delivery by {date}.",
        "Marathi": "{code} मंजूर: {price}/जोडी, एकूण {total_price}. दुकानदाराला कळवले आहे. डिलिव्हरी {date} पर्यंत.",
        "Hindi": "{code} मंज़ूर: {price}/जोड़ी, कुल {total_price}. दुकानदार को बता दिया गया है. डिलीवरी {date} तक.",
    },
    "maker_rejected": {
        "English": "Rejected {code}. The retailer has been told.",
        "Marathi": "{code} नाकारली. दुकानदाराला कळवले आहे.",
        "Hindi": "{code} नामंज़ूर. दुकानदार को बता दिया गया है.",
    },
    "maker_counter_sent": {
        "English": (
            "Counter-offer for {code} sent to the retailer: {price}/pair, total {total_price}, delivery {date}. "
            "We'll tell you when they reply."
        ),
        "Marathi": (
            "{code} साठी नवीन प्रस्ताव दुकानदाराला पाठवला: {price}/जोडी, एकूण {total_price}, डिलिव्हरी {date}. "
            "त्यांचे उत्तर आल्यावर कळवू."
        ),
        "Hindi": (
            "{code} के लिए नया प्रस्ताव दुकानदार को भेज दिया: {price}/जोड़ी, कुल {total_price}, डिलीवरी {date}. "
            "उनका जवाब आने पर बताएंगे."
        ),
    },
    "maker_counter_accepted": {
        "English": (
            "{retailer} accepted your offer for {code}: {total} pairs × {price} = {total_price}. "
            "Order confirmed, delivery by {date}."
        ),
        "Marathi": (
            "{retailer} यांनी {code} साठी तुमचा प्रस्ताव स्वीकारला: {total} जोड्या × {price} = {total_price}. "
            "ऑर्डर कन्फर्म, डिलिव्हरी {date} पर्यंत."
        ),
        "Hindi": (
            "{retailer} ने {code} के लिए आपका प्रस्ताव मान लिया: {total} जोड़ी × {price} = {total_price}. "
            "ऑर्डर कन्फ़र्म, डिलीवरी {date} तक."
        ),
    },
    "maker_counter_declined": {
        "English": "{retailer} declined your offer for {code}. The order is cancelled.",
        "Marathi": "{retailer} यांनी {code} साठी तुमचा प्रस्ताव नाकारला. ऑर्डर रद्द झाली आहे.",
        "Hindi": "{retailer} ने {code} के लिए आपका प्रस्ताव नहीं माना. ऑर्डर रद्द हो गया है.",
    },
    "maker_change_help": {
        "English": (
            "To change {code}, reply like: 3 {code} 2026-12-01 600 "
            "(new date and/or price per pair), or use your dashboard."
        ),
        "Marathi": (
            "{code} बदलण्यासाठी असे पाठवा: 3 {code} 2026-12-01 600 (नवीन तारीख आणि/किंवा प्रति जोडी दर), किंवा डॅशबोर्ड वापरा."
        ),
        "Hindi": (
            "{code} बदलने के लिए ऐसे भेजें: 3 {code} 2026-12-01 600 (नई तारीख और/या प्रति जोड़ी दाम), या डैशबोर्ड इस्तेमाल करें."
        ),
    },
    "maker_nothing_pending": {
        "English": "No order is waiting for your approval.",
        "Marathi": "मंजुरीसाठी कोणतीही ऑर्डर बाकी नाही.",
        "Hindi": "मंज़ूरी के लिए कोई ऑर्डर बाकी नहीं है.",
    },
    "maker_help_offline": {
        "English": (
            "Reply 1 to approve, 2 to reject or 3 to propose a change. "
            "(The assistant for other requests is offline right now. Your dashboard has everything.)"
        ),
        "Marathi": (
            "मंजुरीसाठी 1, नाकारण्यासाठी 2, बदलासाठी 3 पाठवा. (इतर कामांसाठीचा सहाय्यक सध्या बंद आहे. सर्व माहिती डॅशबोर्डवर आहे.)"
        ),
        "Hindi": (
            "मंज़ूरी के लिए 1, मना करने के लिए 2, बदलाव के लिए 3 भेजें. "
            "(बाकी कामों के लिए सहायक अभी बंद है. सारी जानकारी डैशबोर्ड पर है.)"
        ),
    },
    "maker_agent_gave_up": {
        "English": "Sorry, I couldn't finish that. Please try again or use your dashboard.",
        "Marathi": "माफ करा, हे पूर्ण करता आले नाही. पुन्हा प्रयत्न करा किंवा डॅशबोर्ड वापरा.",
        "Hindi": "माफ़ कीजिए, यह पूरा नहीं हो सका. फिर से कोशिश करें या डैशबोर्ड इस्तेमाल करें.",
    },
    "account_approved": {
        "English": (
            "Namaste {name}! {business} is now approved on KarigarSetu. "
            "You can log in to your dashboard with your email and password."
        ),
        "Marathi": (
            "नमस्कार {name}! {business} ला KarigarSetu वर मंजुरी मिळाली आहे. तुमचा ईमेल आणि पासवर्ड वापरून डॅशबोर्डवर लॉगिन करा."
        ),
        "Hindi": ("नमस्ते {name}! {business} को KarigarSetu पर मंज़ूरी मिल गई है. अपने ईमेल और पासवर्ड से डैशबोर्ड पर लॉगिन करें."),
    },
    # ---- to the retailer ----
    "retailer_confirmed": {
        "English": (
            "Your order {code} is confirmed by {maker}.\n{product}, {total} pairs × {price} = {total_price}.\n"
            "Delivery by {date}. We'll send updates here."
        ),
        "Marathi": (
            "तुमची ऑर्डर {code} {maker} यांनी कन्फर्म केली आहे.\n{product}, {total} जोड्या × {price} = {total_price}.\n"
            "डिलिव्हरी {date} पर्यंत. पुढील अपडेट इथेच पाठवू."
        ),
        "Hindi": (
            "आपका ऑर्डर {code} {maker} ने कन्फ़र्म कर दिया है.\n{product}, {total} जोड़ी × {price} = {total_price}.\n"
            "डिलीवरी {date} तक. आगे के अपडेट यहीं भेजेंगे."
        ),
    },
    "retailer_declined": {
        "English": "Sorry, {maker} can't take order {code} right now.{reason} You can try another maker on KarigarSetu.",
        "Marathi": (
            "माफ करा, {maker} सध्या ऑर्डर {code} घेऊ शकत नाहीत.{reason} "
            "तुम्ही KarigarSetu वरील दुसऱ्या कारागिराकडे ऑर्डर देऊ शकता."
        ),
        "Hindi": (
            "माफ़ कीजिए, {maker} अभी ऑर्डर {code} नहीं ले सकते.{reason} आप KarigarSetu पर किसी दूसरे कारीगर को ऑर्डर दे सकते हैं."
        ),
    },
    "reason": {"English": " Reason: {reason}.", "Marathi": " कारण: {reason}.", "Hindi": " कारण: {reason}."},
    "retailer_counter": {
        "English": (
            "{maker} can do order {code} ({total} pairs) at {price}/pair, total {total_price}, "
            "delivery by {date}.{note}\nReply YES to confirm or NO to cancel."
        ),
        "Marathi": (
            "{maker} ऑर्डर {code} ({total} जोड्या) {price}/जोडी दराने करू शकतात, एकूण {total_price}, "
            "डिलिव्हरी {date} पर्यंत.{note}\nकन्फर्म करण्यासाठी 'हो' आणि रद्द करण्यासाठी 'नाही' पाठवा."
        ),
        "Hindi": (
            "{maker} ऑर्डर {code} ({total} जोड़ी) {price}/जोड़ी पर कर सकते हैं, कुल {total_price}, "
            "डिलीवरी {date} तक.{note}\nकन्फ़र्म करने के लिए 'हां' और रद्द करने के लिए 'नहीं' भेजें."
        ),
    },
    "note": {"English": "\nNote: {note}", "Marathi": "\nटीप: {note}", "Hindi": "\nनोट: {note}"},
    "retailer_cancelled": {
        "English": "OK, order {code} is cancelled.",
        "Marathi": "ठीक आहे, ऑर्डर {code} रद्द केली आहे.",
        "Hindi": "ठीक है, ऑर्डर {code} रद्द कर दिया गया है.",
    },
    "status_update": {
        "English": "Update on {code}: {status}.",
        "Marathi": "ऑर्डर {code} अपडेट: {status}.",
        "Hindi": "ऑर्डर {code} अपडेट: {status}.",
    },
    "retailer_offline": {
        "English": "Thanks for your message! Our order assistant is offline right now. The maker will get back to you soon.",
        "Marathi": "तुमच्या संदेशाबद्दल धन्यवाद! आमचा ऑर्डर सहाय्यक सध्या बंद आहे. कारागीर लवकरच तुमच्याशी संपर्क करतील.",
        "Hindi": "आपके संदेश के लिए धन्यवाद! हमारा ऑर्डर सहायक अभी बंद है. कारीगर जल्द ही आपसे संपर्क करेंगे.",
    },
    "retailer_agent_gave_up": {
        "English": "Sorry, I couldn't finish that. The maker will get back to you.",
        "Marathi": "माफ करा, हे पूर्ण करता आले नाही. कारागीर लवकरच संपर्क करतील.",
        "Hindi": "माफ़ कीजिए, यह पूरा नहीं हो सका. कारीगर जल्द ही संपर्क करेंगे.",
    },
    # ---- to anyone ----
    "not_text": {
        "English": "Sorry, I can only read text messages for now. Please type your message.",
        "Marathi": "माफ करा, सध्या फक्त लिहिलेले संदेश वाचता येतात. कृपया तुमचा संदेश टाइप करा.",
        "Hindi": "माफ़ कीजिए, अभी सिर्फ़ लिखे हुए संदेश पढ़े जा सकते हैं. कृपया अपना संदेश टाइप करें.",
    },
}


def t(key: str, lang: str | None = DEFAULT, **values) -> str:
    texts = TEXTS[key]
    return texts.get(norm(lang), texts[DEFAULT]).format(**values)


# ---- guess the language of a message from someone we don't know yet ----

_MARATHI = {
    "आहे",
    "आहेत",
    "मला",
    "हवे",
    "हव्यात",
    "हवेत",
    "पाहिजे",
    "पाहिजेत",
    "जोड्या",
    "जोडी",
    "नाही",
    "किती",
    "तुम्ही",
    "आम्हाला",
    "आणि",
    "करा",
    "द्या",
    "पाठवा",
    "कधी",
    "माझे",
    "माझी",
    "हो",
    "नको",
    "mala",
    "pahije",
    "pahijet",
    "havya",
    "hawya",
    "jodya",
    "jodi",
    "aahe",
    "ahe",
    "kiti",
    "nahi",
    "kara",
    "dya",
    "patha",
    "pathva",
    "amhala",
    "tumhi",
    "kadhi",
}
_HINDI = {
    "है",
    "हैं",
    "मुझे",
    "चाहिए",
    "जोड़ी",
    "जोड़े",
    "नहीं",
    "कितने",
    "कितना",
    "आप",
    "और",
    "करो",
    "करें",
    "दो",
    "भेजो",
    "कब",
    "मेरा",
    "मेरी",
    "हम",
    "हमें",
    "हां",
    "हाँ",
    "भाई",
    "mujhe",
    "chahiye",
    "chaiye",
    "jodi",
    "jode",
    "nahin",
    "kitne",
    "kitna",
    "aap",
    "karo",
    "bhejo",
    "kab",
    "mera",
    "humein",
    "hame",
    "bhai",
    "haan",
    "tak",
    "hai",
    "hain",
}


def detect(text: str) -> str:
    """Best guess: Marathi, Hindi or English, from common words. Ties go to Marathi in Devanagari."""
    words = set(re.findall(r"[\wऀ-ॿ]+", (text or "").lower()))
    mr, hi = len(words & _MARATHI), len(words & _HINDI)
    if mr == hi == 0:
        return "Marathi" if re.search(r"[ऀ-ॿ]", text or "") else DEFAULT
    return "Marathi" if mr >= hi else "Hindi"
