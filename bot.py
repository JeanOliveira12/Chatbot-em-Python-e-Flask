"""
bot.py — O "cérebro": monta o pedido para a IA e interpreta a resposta.

Fluxo de cada mensagem:
  1. Busca trechos relevantes na base de conhecimento (rag.py).
  2. Monta o "system prompt" com as regras do atendente + os trechos encontrados.
  3. Envia o histórico da conversa (é assim que a IA "lembra" do contexto).
  4. A IA pode responder com texto OU chamar a ferramenta "transferir_para_humano".

Sobre "ferramentas" (tool use): em vez de pedir para a IA escrever algo como
"TRANSFERIR" no meio do texto (frágil), declaramos uma ferramenta com um formato
definido. Quando a IA decide transferir, ela devolve um bloco estruturado
{"name": "transferir_para_humano", "input": {"motivo": "..."}} que o código
entende com segurança. É o mesmo mecanismo usado para integrar com sistemas
externos (consultar pedido, agendar festa etc.) — basta declarar mais ferramentas.

Sem ANTHROPIC_API_KEY configurada, o bot roda em "modo demonstração":
responde com o trecho encontrado na base, sem IA. Útil para testar o resto.
"""
import os
import re

import rag

MODELO = os.getenv("MODELO_IA", "claude-haiku-4-5-20251001")
NOME_EMPRESA = os.getenv("NOME_EMPRESA", "Parque Encanto")
MAX_MENSAGENS_HISTORICO = 20  # limita o custo: só as últimas mensagens vão para a IA

REGRAS = f"""Você é o assistente virtual de atendimento do {NOME_EMPRESA}, um parque de diversões.

Regras:
- Responda em português do Brasil, de forma simpática, clara e curta (no máximo 4 frases, salvo se o cliente pedir detalhes).
- Use SOMENTE as informações da seção <base_de_conhecimento>. Se a resposta não estiver lá, diga que não tem essa informação e ofereça transferir para um atendente. Nunca invente preços, horários ou regras.
- Use a ferramenta transferir_para_humano quando: o cliente pedir para falar com uma pessoa; houver reclamação, cobrança, reembolso ou problema com compra; ou você não conseguir resolver depois de tentar.
- Não peça dados sensíveis (CPF, cartão, senhas).
"""

FERRAMENTAS = [
    {
        "name": "transferir_para_humano",
        "description": "Transfere a conversa para um atendente humano. Use quando o cliente pedir, "
                       "em reclamações, reembolsos, problemas com compras, ou quando não souber responder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "motivo": {"type": "string", "description": "Resumo curto do motivo da transferência"}
            },
            "required": ["motivo"],
        },
    }
]

MENSAGEM_TRANSFERENCIA = "Vou te passar para um atendente da nossa equipe. Só um instante, por favor!"


def montar_system_prompt(trechos):
    if trechos:
        base = "\n\n".join(f"### {t['titulo']}\n{t['texto']}" for t in trechos)
    else:
        base = "(Nenhum trecho relevante encontrado para esta pergunta.)"
    return f"{REGRAS}\n<base_de_conhecimento>\n{base}\n</base_de_conhecimento>"


def montar_mensagens(historico):
    """
    Converte o histórico do banco no formato da API:
    lista alternando "user" e "assistant", começando por "user".
    - mensagens do atendente humano entram como "assistant" (com prefixo)
    - mensagens de sistema ficam de fora
    - mensagens seguidas do mesmo papel são unidas
    """
    mensagens = []
    for m in historico[-MAX_MENSAGENS_HISTORICO:]:
        if m["papel"] == "user":
            papel, texto = "user", m["conteudo"]
        elif m["papel"] == "assistant":
            papel, texto = "assistant", m["conteudo"]
        elif m["papel"] == "atendente":
            papel, texto = "assistant", f"[Atendente humano]: {m['conteudo']}"
        else:
            continue
        if mensagens and mensagens[-1]["role"] == papel:
            mensagens[-1]["content"] += "\n\n" + texto
        else:
            mensagens.append({"role": papel, "content": texto})
    while mensagens and mensagens[0]["role"] != "user":
        mensagens.pop(0)
    return mensagens


def responder(historico):
    """
    Recebe o histórico (já incluindo a última mensagem do cliente) e retorna:
      {"texto": str, "transferir": bool, "motivo": str|None, "trechos": [...]}
    """
    ultima_pergunta = next((m["conteudo"] for m in reversed(historico) if m["papel"] == "user"), "")
    trechos = rag.buscar(ultima_pergunta)

    if not os.getenv("ANTHROPIC_API_KEY"):
        return _responder_modo_demo(ultima_pergunta, trechos)

    from anthropic import Anthropic  # importado aqui para o modo demo funcionar sem a lib

    cliente = Anthropic()  # lê a chave da variável de ambiente ANTHROPIC_API_KEY
    resposta = cliente.messages.create(
        model=MODELO,
        max_tokens=600,
        system=montar_system_prompt(trechos),
        messages=montar_mensagens(historico),
        tools=FERRAMENTAS,
    )

    texto, transferir, motivo = [], False, None
    for bloco in resposta.content:
        if bloco.type == "text":
            texto.append(bloco.text)
        elif bloco.type == "tool_use" and bloco.name == "transferir_para_humano":
            transferir, motivo = True, bloco.input.get("motivo")

    texto_final = "\n".join(texto).strip()
    if transferir and not texto_final:
        texto_final = MENSAGEM_TRANSFERENCIA
    return {"texto": texto_final, "transferir": transferir, "motivo": motivo, "trechos": trechos}


def _responder_modo_demo(pergunta, trechos):
    """Resposta sem IA, só para testar o sistema sem chave de API."""
    if re.search(r"\b(atendente|humano|pessoa|reclama|reembolso)", rag.normalizar(pergunta)):
        return {"texto": MENSAGEM_TRANSFERENCIA, "transferir": True,
                "motivo": "Cliente pediu atendimento humano (modo demo)", "trechos": trechos}
    if trechos:
        t = trechos[0]
        texto = f"[Modo demonstração, sem IA] Encontrei isto sobre \"{t['titulo']}\":\n\n{t['texto']}"
    else:
        texto = ("[Modo demonstração, sem IA] Não encontrei essa informação na base. "
                 "Se quiser, posso te transferir para um atendente.")
    return {"texto": texto, "transferir": False, "motivo": None, "trechos": trechos}
