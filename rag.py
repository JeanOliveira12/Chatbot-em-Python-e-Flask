"""
rag.py — Busca na base de conhecimento (a parte "RAG" do projeto).

RAG = Retrieval-Augmented Generation. A ideia:
  1. O cliente pergunta algo.
  2. Buscamos os trechos mais relevantes nos documentos da empresa.
  3. Enviamos esses trechos junto com a pergunta para a IA.
  4. A IA responde com base neles, e não "inventando".

Aqui a busca é por palavras-chave com peso TF-IDF (palavras raras pesam mais).
É simples, não precisa de nenhuma biblioteca extra e funciona bem para bases
pequenas. Numa versão de produção, o próximo passo é trocar por busca com
"embeddings" (busca por significado), usando por exemplo pgvector ou Chroma.
A interface — buscar(pergunta) -> lista de trechos — continua a mesma.

Formato dos documentos: arquivos .md na pasta conhecimento/.
Cada seção que começa com "## " vira um trecho pesquisável.
"""
import math
import re
import unicodedata
from pathlib import Path

PASTA_CONHECIMENTO = Path(__file__).parent / "conhecimento"

# Palavras muito comuns que não ajudam a diferenciar trechos
STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "de", "da", "do", "das", "dos", "e", "em", "no", "na",
    "nos", "nas", "para", "pra", "por", "com", "que", "qual", "quais", "se", "ao", "aos", "eu",
    "voce", "voces", "tem", "ter", "sao", "e", "esta", "isso", "como", "mais", "muito", "meu",
    "minha", "seu", "sua", "ola", "oi", "bom", "boa", "dia", "tarde", "noite", "gostaria",
    "saber", "quero", "queria", "pode", "posso", "vcs", "ja", "nao", "sim",
}


def normalizar(texto):
    """Minúsculas e sem acento: 'Ingressos' e 'ingressos' viram iguais."""
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def tokens(texto):
    palavras = re.findall(r"[a-z0-9]+", normalizar(texto))
    # remove stopwords e corta um 's' final simples (ingressos -> ingresso)
    return [p.rstrip("s") if len(p) > 4 else p for p in palavras if p not in STOPWORDS and len(p) > 1]


def carregar_trechos():
    """Lê todos os .md e quebra em trechos por seção '## '."""
    trechos = []
    for arquivo in sorted(PASTA_CONHECIMENTO.glob("*.md")):
        titulo_atual, linhas = None, []
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            if linha.startswith("## "):
                if titulo_atual:
                    trechos.append(_montar(arquivo.name, titulo_atual, linhas))
                titulo_atual, linhas = linha[3:].strip(), []
            elif titulo_atual:
                linhas.append(linha)
        if titulo_atual:
            trechos.append(_montar(arquivo.name, titulo_atual, linhas))
    return trechos


def _montar(fonte, titulo, linhas):
    texto = "\n".join(linhas).strip()
    # o título conta duas vezes: palavras do título são bons indicadores do assunto
    return {"fonte": fonte, "titulo": titulo, "texto": texto, "tokens": tokens(f"{titulo} {titulo} {texto}")}


def buscar(pergunta, k=3):
    """Retorna os k trechos mais relevantes para a pergunta."""
    trechos = carregar_trechos()  # relê sempre: edições no painel valem na hora
    termos = set(tokens(pergunta))
    if not trechos or not termos:
        return []

    # IDF: quanto mais rara a palavra entre os trechos, maior o peso
    n = len(trechos)
    idf = {}
    for termo in termos:
        aparece_em = sum(1 for t in trechos if termo in t["tokens"])
        idf[termo] = math.log((n + 1) / (aparece_em + 1)) + 1 if aparece_em else 0

    resultados = []
    for t in trechos:
        pontuacao = sum(idf[termo] * t["tokens"].count(termo) ** 0.5 for termo in termos if termo in t["tokens"])
        if pontuacao > 0:
            resultados.append((pontuacao, t))

    resultados.sort(key=lambda x: x[0], reverse=True)
    return [{"fonte": t["fonte"], "titulo": t["titulo"], "texto": t["texto"], "pontuacao": round(p, 2)}
            for p, t in resultados[:k]]
