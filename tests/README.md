# Tests

Plain Python 3, no installs. Anvil is stubbed in `support.py`. From the repo root:

```sh
python3 -m unittest
```

Optional: [anvil-cli](https://anvil.works) checks templates and syntax, and syncs to the editor.

```sh
curl -fsSL https://anvil.works/install-cli.sh | sh
anvil validate .
anvil watch
```

Neither catches Python that Skulpt (the browser's Python) lacks, such as `str.casefold()`. `test_static.py` covers the known cases.
