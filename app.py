"""
app.py — Servidor web (Flask).

Separação em camadas (é isso que torna o projeto "evoluível"):
  - app.py  -> rotas HTTP (site, API, painel). Não sabe nada de IA.
  - bot.py  -> lógica do atendente com IA. Não sabe nada de HTTP.
  - rag.py  -> busca na base de conhecimento.
  - db.py   -> banco de dados.

Para adicionar WhatsApp no futuro, por exemplo, cria-se uma rota de webhook que
recebe a mensagem do WhatsApp e chama a MESMA função processar_mensagem().
O bot não muda.
"""
import os
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for

load_dotenv()  # carrega variáveis do arquivo .env

import bot  # noqa: E402  (precisa vir depois do load_dotenv)
import db  # noqa: E402
import rag  # noqa: E402

app = Flask(__name__)
db.iniciar_banco()


# ---------------------------------------------------------------------------
# Lógica central: usada pelo site e, no futuro, por WhatsApp/outros canais
# ---------------------------------------------------------------------------
def processar_mensagem(conversa_id, texto):
    conversa = db.obter_conversa(conversa_id)
    db.salvar_mensagem(conversa_id, "user", texto)

    # Conversa já transferida: o bot não responde, o atendente responde pelo painel
    if conversa["status"] != "bot":
        return {"status": conversa["status"]}

    try:
        resultado = bot.responder(db.mensagens_da_conversa(conversa_id))
    except Exception as erro:  # falha na API de IA não pode derrubar o atendimento
        app.logger.exception("Erro ao chamar a IA: %s", erro)
        resultado = {"texto": "Tive um problema técnico agora. Vou te passar para um atendente.",
                     "transferir": True, "motivo": "Erro técnico na IA"}

    if resultado["texto"]:
        db.salvar_mensagem(conversa_id, "assistant", resultado["texto"])
    if resultado["transferir"]:
        db.atualizar_status(conversa_id, "humano", resultado.get("motivo"))
        db.salvar_mensagem(conversa_id, "sistema", "Conversa transferida para atendimento humano.")
    return {"status": db.obter_conversa(conversa_id)["status"]}


# ---------------------------------------------------------------------------
# Site do cliente + API do chat
# ---------------------------------------------------------------------------
@app.get("/")
def pagina_chat():
    return render_template("chat.html", empresa=bot.NOME_EMPRESA)


@app.post("/api/conversas")
def api_criar_conversa():
    return jsonify({"conversa_id": db.criar_conversa()}), 201


@app.post("/api/conversas/<int:conversa_id>/mensagens")
def api_enviar_mensagem(conversa_id):
    if not db.obter_conversa(conversa_id):
        abort(404)
    texto = (request.get_json(silent=True) or {}).get("texto", "").strip()
    if not texto:
        return jsonify({"erro": "Mensagem vazia"}), 400
    if len(texto) > 2000:
        return jsonify({"erro": "Mensagem muito longa"}), 400
    return jsonify(processar_mensagem(conversa_id, texto))


@app.get("/api/conversas/<int:conversa_id>/mensagens")
def api_listar_mensagens(conversa_id):
    """O chat consulta esta rota a cada poucos segundos para ver respostas novas."""
    conversa = db.obter_conversa(conversa_id)
    if not conversa:
        abort(404)
    depois = request.args.get("depois", 0, type=int)
    return jsonify({"status": conversa["status"], "mensagens": db.mensagens_da_conversa(conversa_id, depois)})


# ---------------------------------------------------------------------------
# Painel administrativo (protegido por senha)
# ---------------------------------------------------------------------------
def exige_login(funcao):
    @wraps(funcao)
    def verificar(*args, **kwargs):
        senha = os.getenv("ADMIN_SENHA", "admin")
        auth = request.authorization
        if not auth or auth.username != "admin" or auth.password != senha:
            return Response("Acesso restrito", 401, {"WWW-Authenticate": 'Basic realm="Painel"'})
        return funcao(*args, **kwargs)
    return verificar


@app.get("/admin")
@exige_login
def admin_conversas():
    return render_template("admin_conversas.html", conversas=db.listar_conversas(), empresa=bot.NOME_EMPRESA)


@app.get("/admin/conversas/<int:conversa_id>")
@exige_login
def admin_conversa(conversa_id):
    conversa = db.obter_conversa(conversa_id) or abort(404)
    return render_template("admin_conversa.html", conversa=conversa,
                           mensagens=db.mensagens_da_conversa(conversa_id), empresa=bot.NOME_EMPRESA)


@app.post("/admin/conversas/<int:conversa_id>/responder")
@exige_login
def admin_responder(conversa_id):
    db.obter_conversa(conversa_id) or abort(404)
    texto = request.form.get("texto", "").strip()
    if texto:
        db.salvar_mensagem(conversa_id, "atendente", texto)
    return redirect(url_for("admin_conversa", conversa_id=conversa_id))


@app.post("/admin/conversas/<int:conversa_id>/status")
@exige_login
def admin_status(conversa_id):
    db.obter_conversa(conversa_id) or abort(404)
    novo = request.form.get("status")
    avisos = {"bot": "O assistente virtual voltou a atender.", "encerrada": "Atendimento encerrado."}
    if novo in avisos:
        db.atualizar_status(conversa_id, novo)
        db.salvar_mensagem(conversa_id, "sistema", avisos[novo])
    return redirect(url_for("admin_conversa", conversa_id=conversa_id))


@app.route("/admin/conhecimento", methods=["GET", "POST"])
@exige_login
def admin_conhecimento():
    pasta = rag.PASTA_CONHECIMENTO
    arquivos = sorted(p.name for p in pasta.glob("*.md"))
    nome = request.values.get("arquivo") or (arquivos[0] if arquivos else None)
    if nome and (Path(nome).name != nome or not nome.endswith(".md")):
        abort(400)  # evita acessar arquivos fora da pasta

    salvo = False
    if request.method == "POST" and nome:
        (pasta / nome).write_text(request.form.get("conteudo", ""), encoding="utf-8")
        salvo = True
        if nome not in arquivos:
            arquivos = sorted(arquivos + [nome])

    conteudo = (pasta / nome).read_text(encoding="utf-8") if nome and (pasta / nome).exists() else ""
    teste = request.args.get("teste", "").strip()
    resultados = rag.buscar(teste) if teste else None
    return render_template("admin_conhecimento.html", arquivos=arquivos, atual=nome, conteudo=conteudo,
                           salvo=salvo, teste=teste, resultados=resultados, empresa=bot.NOME_EMPRESA)


if __name__ == "__main__":
    modo = "IA (" + bot.MODELO + ")" if os.getenv("ANTHROPIC_API_KEY") else "DEMONSTRAÇÃO (sem chave de API)"
    print(f"\n  Chatbot rodando em modo: {modo}")
    print("  Chat:   http://localhost:5000")
    print("  Painel: http://localhost:5000/admin  (usuário: admin)\n")
    app.run(debug=True)
