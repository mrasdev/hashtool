from hashtool.cli import main


def test_main_returns_zero_and_prints_hello(capsys):
    retval = main()

    captured = capsys.readouterr()
    assert retval == 0
    assert captured.out == "Hello\n"
