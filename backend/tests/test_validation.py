"""The shared field rules (app/validation.py) used by sign-up, the contact form and add-a-design."""
import pytest
from fastapi import HTTPException

from app.services import validation as V


def bad(fn, *args):
    with pytest.raises(HTTPException) as e:
        fn(*args)
    return e.value.detail


@pytest.mark.parametrize("value", ["Rahul Patil", "तृप्ती भोसले", "D'Souza-Patil Jr.", "  Asha   Rao "])
def test_person_name_ok(value):
    assert V.person_name(value) == " ".join(value.split())


@pytest.mark.parametrize("value,msg", [("", "enter your name"), ("A", "enter your name"), ("12", "letters"),
                                       ("<b>x</b>", "letters"), ("x" * 101, "too long")])
def test_person_name_bad(value, msg):
    assert msg in bad(V.person_name, value)


def test_business_and_place():
    assert V.business_name("Shinde & Sons Footwear (Unit 2)") == "Shinde & Sons Footwear (Unit 2)"
    assert "letters" in bad(V.business_name, "1234")
    assert V.place_or_craft("Kolhapur", "town or city") == "Kolhapur"
    assert "town or city" in bad(V.place_or_craft, "@@", "town or city").lower()


@pytest.mark.parametrize("raw,digits", [("98220 12345", "919822012345"), ("+91 98220-12345", "919822012345"),
                                        ("098220 12345", "919822012345"), ("+1 315 886 5652", "13158865652")])
def test_whatsapp_ok(raw, digits):
    assert V.whatsapp(raw) == digits


@pytest.mark.parametrize("raw,msg", [("", "enter your WhatsApp"), ("abc", "digits"), ("12345", "valid WhatsApp"),
                                     ("12345 67890", "start with 6, 7, 8 or 9")])
def test_whatsapp_bad(raw, msg):
    assert msg in bad(V.whatsapp, raw)


@pytest.mark.parametrize("value", ["a@b.c", "a..b@shop.in", "no-at.in", "x@shop", "a b@shop.in"])
def test_email_bad(value):
    assert "valid email" in bad(V.email, value)


def test_email_ok_and_lowercased():
    assert V.email("  Trupti@KarigarSetu.co.in ") == "trupti@karigarsetu.co.in"


@pytest.mark.parametrize("pw,msg", [("short1", "at least 8"), ("onlyletters", "letter and one number"),
                                    ("12345678", "letter and one number"), (" goodpass1", "space"),
                                    ("a1" * 40, "too long")])
def test_password_bad(pw, msg):
    assert msg in bad(V.new_password, pw)


def test_password_not_email():
    assert "same as your email" in bad(V.new_password, "asha123@x.in", "asha123@x.in")
    assert V.new_password("goodpass123") == "goodpass123"


def test_design_fields():
    assert V.design_name("Kolhapuri Classic 2") == "Kolhapuri Classic 2"
    assert V.whole_number("550", "Price per pair", 1, 100000) == 550
    assert "between 1 and 100,000" in bad(V.whole_number, 1000000, "Price per pair", 1, 100000)
    assert "whole number" in bad(V.whole_number, "abc", "Price per pair", 1, 100000)
    assert "whole number" in bad(V.whole_number, 5.5, "Pairs per day", 1, 1000)
    assert V.sizes("10, 6 7,8") == [6, 7, 8, 10]
    assert "only once" in bad(V.sizes, "6,6,7")
    assert "between 1 and 15" in bad(V.sizes, "6,20")
