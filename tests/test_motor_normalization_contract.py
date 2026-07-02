from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path


MOTOR_FILE = Path(__file__).resolve().parents[1] / "app" / "motor" / "btdigg" / "rd_turbo_pro.py"


def load_motor_module():
    module_name = f"rd_turbo_pro_normalization_contract_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MOTOR_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_unifies_case_accents_n_and_separators():
    motor = load_motor_module()

    assert motor.normalize("La Niña.del-Día_[2024]") == "la nina del dia 2024"
    assert motor.normalize("WEB-DL DTS_HD ES/EN") == "web dl dts hd es en"
    assert motor.normalize("MÁQUINA_de guerra") == "maquina de guerra"


def test_word_hit_accepts_separator_and_compact_variants():
    motor = load_motor_module()

    for text in ("Ultra HD", "Ultra-HD", "Ultra_HD", "Ultra.HD", "UltraHD"):
        assert motor._word_hit("ultra hd", text)

    for text in ("WEB-DL", "WEB DL", "WEB_DL", "WEBDL"):
        assert motor._word_hit("web-dl", text)
        assert motor._word_hit("web dl", text)

    for text in ("DTS-HD", "DTS HD", "DTS_HD", "DTSHD"):
        assert motor._word_hit("dts-hd", text)
        assert motor._word_hit("dts hd", text)

    assert motor._word_hit("blu-ray", "Blu Ray")
    assert motor._word_hit("blu ray", "BluRay")
    assert motor._word_hit("hdr10 plus", "HDR10Plus")


def test_word_hit_keeps_short_bad_word_boundaries():
    motor = load_motor_module()

    assert not motor._word_hit("cam", "camino")
    assert motor._word_hit("cam", "cam-rip")
    assert motor._word_hit("cam", "cam_rip")
    assert not motor._word_hit("ts", "dts hd")
    assert motor._word_hit("ts", "ts screener")


def test_query_matching_ignores_accents_and_common_separators():
    motor = load_motor_module()
    terms = motor.terms_from_query_for_match("La niña del día 2024")

    assert terms == ["nina", "del", "dia", "2024"]
    for title in ("La.nina-del_dia.2024", "La/niña_del-día 2024", "La nina del dia 2024"):
        assert motor._match_ratio(terms, title) == (1.0, ["nina", "del", "dia", "2024"])

    freddy_terms = motor.terms_from_query_for_match("Five Nights at Freddys")
    ratio, hits = motor._match_ratio(freddy_terms, "Five Nights at Freddy's 2")
    assert ratio == 1.0
    assert hits == ["five", "nights", "freddys"]


def test_query_terms_drop_release_noise_without_losing_identity():
    motor = load_motor_module()

    assert motor.terms_from_query_for_match(
        "Snatch.2000.2160p.AMZN.WEB-DL.x265.10bit.HDR10Plus.DTS-HD.MA.5.1-SWTYBLZ"
    ) == ["snatch", "2000"]
    assert motor.terms_from_query_for_match(
        "Malditos bastardos 4K UHDremux 2160p HDR10 DTS 5.1 Castellano DTS-HD 5.1 Ingles Subs ES-EN"
    ) == ["malditos", "bastardos"]
    assert motor.terms_from_query_for_match("Mad Max 2015 2160p HMAX WEB-DL") == ["mad", "max", "2015"]


def test_btdigg_search_query_is_normalized_for_remote_search():
    motor = load_motor_module()

    assert motor.btdigg_search_query("La Niña.del-Día") == "la nina del dia"
    assert motor.btdigg_search_query("Malditos.bastardos") == "malditos bastardos"
    assert motor.btdigg_search_query("WEB-DL DTS_HD") == "web dl dts hd"
    assert motor.btdigg_search_query("Snatch.2000.2160p.AMZN.WEB-DL.x265.10bit.HDR10Plus") == (
        "snatch 2000 2160p amzn web dl x265 10bit hdr10plus"
    )


def test_quality_marker_detection_uses_central_matching():
    motor = load_motor_module()

    for query in ("Ultra HD", "Ultra-HD", "Ultra_HD", "UltraHD", "Blu-Ray", "Blu Ray", "x265"):
        assert motor._query_has_quality_marker(query)
    assert not motor._word_hit("4k", "wolfmax4k.com")
    assert motor._word_hit("uhd", "4KUHD")
