"""Escrita e leitura determinísticas de JSON (SPEC §6).

Regras: UTF-8 sem BOM, ``ensure_ascii=False``, ``\\n`` como fim de linha,
chaves em ordem alfabética. ``base/`` e ``fontes/`` usam ``indent=1``;
``docs/dados/`` e as linhas de ``base/normas.jsonl`` são compactos.
"""
from __future__ import annotations

import json
import os
import pathlib

__all__ = [
    "dumps", "dumps_compacto", "linha_jsonl", "texto_jsonl",
    "escrever_texto", "escrever_json", "escrever_jsonl",
    "ler_json", "ler_jsonl", "escrita_atomica",
]


def dumps(obj) -> str:
    """JSON legível (``indent=1``), chaves ordenadas, terminado em ``\\n``."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def dumps_compacto(obj, fim: str = "\n") -> str:
    """JSON compacto (``separators=(',', ':')``), chaves ordenadas."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + fim


def linha_jsonl(obj) -> str:
    """Uma linha JSONL compacta, com ``\\n`` no fim."""
    return dumps_compacto(obj, "\n")


def texto_jsonl(objs) -> str:
    return "".join(linha_jsonl(o) for o in objs)


def escrita_atomica(caminho, dados: bytes) -> None:
    """Grava ``dados`` num arquivo temporário irmão e troca com ``os.replace``."""
    caminho = pathlib.Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(f".{caminho.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "wb") as f:
            f.write(dados)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, caminho)
    finally:
        if tmp.exists():
            tmp.unlink()


def escrever_texto(caminho, texto: str) -> None:
    """Grava texto em UTF-8 (sem BOM), com ``\\n``, de forma atômica."""
    if "\r" in texto:
        texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    escrita_atomica(caminho, texto.encode("utf-8"))


def escrever_json(caminho, obj, compacto: bool = False) -> None:
    escrever_texto(caminho, dumps_compacto(obj) if compacto else dumps(obj))


def escrever_jsonl(caminho, objs) -> None:
    escrever_texto(caminho, texto_jsonl(objs))


def ler_json(caminho):
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def ler_jsonl(caminho) -> list:
    saida = []
    with open(caminho, "r", encoding="utf-8") as f:
        for n, linha in enumerate(f, 1):
            linha = linha.strip()
            if not linha:
                continue
            try:
                saida.append(json.loads(linha))
            except json.JSONDecodeError as e:
                raise ValueError(f"{caminho}: linha {n}: JSON inválido ({e})") from None
    return saida
