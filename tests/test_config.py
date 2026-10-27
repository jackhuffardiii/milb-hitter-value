"""pipeline/config.py is the single source for methodology knobs: modules must read it, not hold their own copy."""
from pipeline import b2_war, b4_mle, b17_pitch_war, b18_pitch_mle, b22_pitch_models, config


def test_modules_read_config():
    assert b2_war.POS_WAR_PER_2430 == config.POS_WAR_PER_2430 and b17_pitch_war.PITCH_WAR_PER_2430 == config.PITCH_WAR_PER_2430
    assert b4_mle.K_STAB is config.K_STAB_HIT and b18_pitch_mle.K_STAB is config.K_STAB_PITCH
    assert b4_mle.MIN_PA == config.MIN_PAIR and b22_pitch_models.MIN_AAA_BIP == config.CONTACT_MIN_AAA_BIP


def test_no_stray_literals():
    """The knobs' old literals should not reappear in the modules that now read config."""
    import pathlib
    src = {p.name: p.read_text() for p in pathlib.Path(config.__file__).parent.glob("b*.py")}
    assert ">= 150" not in src["b5_features.py"] and ">= 150" not in src["b20_pitch_features.py"]
    assert "= 590" not in src["b2_war.py"] and "= 410" not in src["b17_pitch_war.py"]
