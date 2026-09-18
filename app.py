import streamlit as st
import base64, sqlite3, hashlib
from pathlib import Path
from datetime import datetime

ROOT=Path(__file__).resolve().parent
DATA=ROOT/"data"; DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/"esteira.db"
ETAPAS=["BASE","FOTO","FÍSICA","VÍDEO","PROMO","ADS"]
PERFIS=["ADMINISTRADOR","GESTOR","FUNCIONÁRIO"]
PRIORIDADES=["NORMAL","PRIORIDADE","URGENTE"]
PESO_PRI={"URGENTE":0,"PRIORIDADE":1,"NORMAL":2}


def _img_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

logo_b64 = _img_b64("logo_abxon.jpg")

st.set_page_config(page_title="Esteira ABX-ON",page_icon="favicon_abxon.png",layout="wide")

def con():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON"); return c
def now(): return datetime.now().isoformat(timespec="seconds")
def sh(s): return hashlib.sha256(s.encode()).hexdigest()
def fmt(v):
    try:return datetime.fromisoformat(v).strftime("%d/%m/%Y %H:%M") if v else "—"
    except:return v or "—"
def age(v):
    if not v:return "—"
    try:m=max(0,int((datetime.now()-datetime.fromisoformat(v)).total_seconds()/60))
    except:return "—"
    if m<60:return f"{m} min"
    if m<1440:return f"{m//60}h {m%60:02d}min"
    return f"{m//1440}d {(m%1440)//60}h"
def col_exists(c,t,col): return col in [r["name"] for r in c.execute(f"PRAGMA table_info({t})")]
def table_exists(c,t): return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone() is not None

def init():
    with con() as c:
        # base tables
        c.executescript("""
        CREATE TABLE IF NOT EXISTS produtos(sku TEXT PRIMARY KEY,altura REAL,largura REAL,comprimento REAL,peso REAL,criado_em TEXT);
        CREATE TABLE IF NOT EXISTS anuncios(id INTEGER PRIMARY KEY AUTOINCREMENT,sku TEXT,numero INTEGER,titulo TEXT,descricao TEXT,preco REAL,etapa TEXT DEFAULT 'BASE',status TEXT DEFAULT 'AGUARDANDO',link_foto TEXT,link_video TEXT,criado_em TEXT,atualizado_em TEXT,UNIQUE(sku,numero));
        CREATE TABLE IF NOT EXISTS historico(id INTEGER PRIMARY KEY AUTOINCREMENT,anuncio_id INTEGER,data_hora TEXT,etapa TEXT,acao TEXT,observacao TEXT);
        """)
        # V6: dados compartilhados por SKU nas etapas pós-BASE.
        for n,t in [("foto_padrao","TEXT"),("video_padrao","TEXT"),("promo_padrao","TEXT"),("ads_padrao","TEXT")]:
            if not col_exists(c,"produtos",n):
                c.execute(f"ALTER TABLE produtos ADD COLUMN {n} {t}")
        for n,t in [("foto_override","TEXT"),("video_override","TEXT"),("promo_override","TEXT"),("ads_override","TEXT")]:
            if not col_exists(c,"anuncios",n):
                c.execute(f"ALTER TABLE anuncios ADD COLUMN {n} {t}")
        # migrate anuncios
        for n,t,default in [
            ("responsavel","TEXT",None),("entrada_etapa_em","TEXT",None),("inicio_etapa_em","TEXT",None),
            ("prioridade","TEXT","'NORMAL'"),("prazo","TEXT",None),("correcao_origem","TEXT",None),
            ("correcao_destino","TEXT",None),("correcao_retorno","TEXT",None),("correcao_motivo","TEXT",None)]:
            if not col_exists(c,"anuncios",n):
                c.execute(f"ALTER TABLE anuncios ADD COLUMN {n} {t}"+(f" DEFAULT {default}" if default else ""))
        c.execute("UPDATE anuncios SET prioridade=COALESCE(prioridade,'NORMAL')")
        c.execute("UPDATE anuncios SET entrada_etapa_em=COALESCE(entrada_etapa_em,atualizado_em,criado_em,?)",(now(),))

        # robust V2/V4 usuarios migration
        if table_exists(c,"usuarios"):
            cols=[r["name"] for r in c.execute("PRAGMA table_info(usuarios)")]
            if "login" not in cols:
                c.execute("ALTER TABLE usuarios RENAME TO usuarios_legado")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS usuarios(
          id INTEGER PRIMARY KEY AUTOINCREMENT,nome TEXT NOT NULL,login TEXT UNIQUE NOT NULL,senha TEXT NOT NULL,
          perfil TEXT NOT NULL DEFAULT 'FUNCIONÁRIO',ativo INTEGER NOT NULL DEFAULT 1,criado_em TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS usuario_etapas(
          usuario_id INTEGER NOT NULL,etapa TEXT NOT NULL,UNIQUE(usuario_id,etapa),
          FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE);
        """)
        if table_exists(c,"usuarios_legado"):
            for r in c.execute("SELECT * FROM usuarios_legado").fetchall():
                nome=r["nome"] if "nome" in r.keys() else f"Usuário {r['id']}"
                login="".join(ch.lower() for ch in nome if ch.isalnum()) or f"user{r['id']}"
                base=login; k=1
                while c.execute("SELECT 1 FROM usuarios WHERE login=?",(login,)).fetchone():
                    k+=1;login=f"{base}{k}"
                c.execute("INSERT INTO usuarios(nome,login,senha,perfil,ativo,criado_em) VALUES(?,?,?,'FUNCIONÁRIO',1,?)",(nome,login,sh("abxon123"),now()))
            c.execute("DROP TABLE usuarios_legado")
        if c.execute("SELECT COUNT(*) n FROM usuarios WHERE perfil='ADMINISTRADOR'").fetchone()["n"]==0:
            login="admin"
            if c.execute("SELECT 1 FROM usuarios WHERE login='admin'").fetchone(): login="adminmpx"
            c.execute("INSERT INTO usuarios(nome,login,senha,perfil,ativo,criado_em) VALUES('Administrador ABX-ON',?,?, 'ADMINISTRADOR',1,?)",(login,sh("abxon123"),now()))

def log(c,i,e,a,o=""): c.execute("INSERT INTO historico(anuncio_id,data_hora,etapa,acao,observacao) VALUES(?,?,?,?,?)",(i,now(),e,a,o))
def perms(uid):
    with con() as c:return [r["etapa"] for r in c.execute("SELECT etapa FROM usuario_etapas WHERE usuario_id=?",(uid,))]
def criar_user(nome,login,senha,perfil,ets):
    with con() as c:
        cur=c.execute("INSERT INTO usuarios(nome,login,senha,perfil,ativo,criado_em) VALUES(?,?,?,?,1,?)",(nome,login,sh(senha),perfil,now()))
        for e in ets:c.execute("INSERT INTO usuario_etapas VALUES(?,?)",(cur.lastrowid,e))
def update_user(uid,nome,perfil,ativo,ets,senha=""):
    with con() as c:
        c.execute("UPDATE usuarios SET nome=?,perfil=?,ativo=? WHERE id=?",(nome,perfil,int(ativo),uid))
        if senha:c.execute("UPDATE usuarios SET senha=? WHERE id=?",(sh(senha),uid))
        c.execute("DELETE FROM usuario_etapas WHERE usuario_id=?",(uid,))
        for e in ets:c.execute("INSERT INTO usuario_etapas VALUES(?,?)",(uid,e))

def criar_anuncios(sku,q,ts,ds,ps,user,prioridade,prazo):
    with con() as c:
        t=now();c.execute("INSERT OR IGNORE INTO produtos(sku,criado_em) VALUES(?,?)",(sku,t))
        n=c.execute("SELECT COALESCE(MAX(numero),0)n FROM anuncios WHERE sku=?",(sku,)).fetchone()["n"]
        for j in range(q):
            cur=c.execute("""INSERT INTO anuncios(sku,numero,titulo,descricao,preco,etapa,status,criado_em,atualizado_em,entrada_etapa_em,prioridade,prazo)
            VALUES(?,?,?,?,?,'BASE','AGUARDANDO',?,?,?,?,?)""",(sku,n+j+1,ts[j],ds[j],ps[j],t,t,t,prioridade,prazo or None))
            log(c,cur.lastrowid,"BASE","ANÚNCIO CRIADO",user["nome"])

def abrir(i,user):
    with con() as c:
        a=c.execute("SELECT * FROM anuncios WHERE id=?",(i,)).fetchone()
        if not a["inicio_etapa_em"]:
            t=now()
            tem_correcao=bool(a["correcao_retorno"] or a["correcao_origem"] or a["correcao_destino"])
            novo_status="CORRIGIR" if tem_correcao else "EM ANDAMENTO"
            c.execute("UPDATE anuncios SET inicio_etapa_em=?,responsavel=?,status=?,atualizado_em=? WHERE id=?",
                      (t,user["nome"],novo_status,t,i))
            log(c,i,a["etapa"],"CORREÇÃO ABERTA" if tem_correcao else "TRABALHO ABERTO",user["nome"])

def validar(etapa,campos):
    if etapa=="BASE":
        if not campos["titulo"].strip():return "Preencha o título."
        if not campos["descricao"].strip():return "Preencha a descrição."
        if campos["preco"]<=0:return "Informe um preço maior que zero."
    elif etapa=="FOTO" and not campos["foto"].strip():return "Informe o link da foto."
    elif etapa=="FÍSICA" and any(campos[k]<=0 for k in ["altura","largura","comprimento","peso"]):return "Preencha altura, largura, comprimento e peso."
    elif etapa=="VÍDEO" and not campos["video"].strip():return "Informe o link do vídeo."
    return None

def finalizar(i,user,campos):
    with con() as c:
        a=c.execute("SELECT * FROM anuncios WHERE id=?",(i,)).fetchone()
        erro=validar(a["etapa"],campos)
        if erro:return erro
        if a["etapa"]=="BASE":c.execute("UPDATE anuncios SET titulo=?,descricao=?,preco=? WHERE id=?",(campos["titulo"],campos["descricao"],campos["preco"],i))
        elif a["etapa"]=="FOTO":c.execute("UPDATE anuncios SET link_foto=? WHERE id=?",(campos["foto"],i))
        elif a["etapa"]=="FÍSICA":c.execute("UPDATE produtos SET altura=?,largura=?,comprimento=?,peso=? WHERE sku=?",(campos["altura"],campos["largura"],campos["comprimento"],campos["peso"],a["sku"]))
        elif a["etapa"]=="VÍDEO":c.execute("UPDATE anuncios SET link_video=? WHERE id=?",(campos["video"],i))
        atual=a["etapa"];t=now();log(c,i,atual,"ETAPA CONCLUÍDA",user["nome"])
        # V5.1: correção sempre retorna diretamente para a etapa que solicitou.
        # V5.3: a etapa que pediu a correção tem prioridade absoluta sobre o fluxo normal.
        retorno=a["correcao_retorno"] or a["correcao_origem"]
        motivo_original=a["correcao_motivo"]
        eh_correcao=bool(a["correcao_retorno"] or a["correcao_origem"] or a["correcao_destino"])
        if eh_correcao and retorno:
            c.execute("""UPDATE anuncios SET etapa=?,status='AGUARDANDO',responsavel=NULL,entrada_etapa_em=?,inicio_etapa_em=NULL,
            atualizado_em=?,correcao_origem=NULL,correcao_destino=NULL,correcao_retorno=NULL,correcao_motivo=NULL WHERE id=?""",(retorno,t,t,i))
            log(c,i,retorno,"CORREÇÃO CONCLUÍDA / RETORNO DIRETO",
                f"{user['nome']} corrigiu em {atual}. Motivo original: {motivo_original or '—'}")
            return None
        k=ETAPAS.index(atual)
        if k==len(ETAPAS)-1:
            c.execute("UPDATE anuncios SET status='OK',responsavel=?,atualizado_em=? WHERE id=?",(user["nome"],t,i));log(c,i,"ADS","ANÚNCIO FINALIZADO",user["nome"])
        else:
            e=ETAPAS[k+1];c.execute("UPDATE anuncios SET etapa=?,status='AGUARDANDO',responsavel=NULL,entrada_etapa_em=?,inicio_etapa_em=NULL,atualizado_em=? WHERE id=?",(e,t,t,i));log(c,i,e,"TRABALHO RECEBIDO")
        return None

def enviar_correcao(i,user,destino,motivo):
    with con() as c:
        a=c.execute("SELECT * FROM anuncios WHERE id=?",(i,)).fetchone();t=now()
        c.execute("""UPDATE anuncios SET etapa=?,status='CORRIGIR',responsavel=NULL,entrada_etapa_em=?,inicio_etapa_em=NULL,
        atualizado_em=?,correcao_origem=?,correcao_destino=?,correcao_retorno=?,correcao_motivo=? WHERE id=?""",
        (destino,t,t,a["etapa"],destino,a["etapa"],motivo,i))
        log(c,i,destino,"CORREÇÃO SOLICITADA",f"{user['nome']} | origem {a['etapa']} | {motivo}")

def fila(etapa):
    with con() as c:rows=c.execute("SELECT * FROM anuncios WHERE etapa=? AND status!='OK'",(etapa,)).fetchall()
    return sorted(rows,key=lambda x:(0 if x["status"]=="CORRIGIR" else 1,PESO_PRI.get(x["prioridade"],2),x["entrada_etapa_em"] or ""))


def anuncios_do_sku_na_etapa(sku,etapa):
    with con() as c:
        return c.execute("SELECT * FROM anuncios WHERE sku=? AND etapa=? AND status!='OK' ORDER BY numero",(sku,etapa)).fetchall()

def finalizar_grupo(sku,etapa,user,campos,personalizados=None):
    """Finaliza todos os anúncios do mesmo SKU que estão juntos na etapa.
    personalizados: dict anuncio_id -> valor específico para FOTO/VÍDEO/PROMO/ADS.
    """
    personalizados=personalizados or {}
    with con() as c:
        grupo=c.execute("SELECT * FROM anuncios WHERE sku=? AND etapa=? AND status!='OK' ORDER BY numero",(sku,etapa)).fetchall()
        if not grupo:return "Nenhum anúncio disponível nesta etapa."
        p=c.execute("SELECT * FROM produtos WHERE sku=?",(sku,)).fetchone()
        if etapa=="FOTO" and not campos.get("foto","").strip():return "Informe o link da foto."
        if etapa=="VÍDEO" and not campos.get("video","").strip():return "Informe o link do vídeo."
        if etapa=="FÍSICA" and any(float(campos.get(k,0) or 0)<=0 for k in ["altura","largura","comprimento","peso"]):
            return "Preencha altura, largura, comprimento e peso."
        if etapa=="FOTO": c.execute("UPDATE produtos SET foto_padrao=? WHERE sku=?",(campos["foto"],sku))
        if etapa=="VÍDEO": c.execute("UPDATE produtos SET video_padrao=? WHERE sku=?",(campos["video"],sku))
        if etapa=="PROMO": c.execute("UPDATE produtos SET promo_padrao=? WHERE sku=?",(campos.get("promo",""),sku))
        if etapa=="ADS": c.execute("UPDATE produtos SET ads_padrao=? WHERE sku=?",(campos.get("ads",""),sku))
        if etapa=="FÍSICA":
            c.execute("UPDATE produtos SET altura=?,largura=?,comprimento=?,peso=? WHERE sku=?",
                      (campos["altura"],campos["largura"],campos["comprimento"],campos["peso"],sku))
    # Reuse the already-tested per-ad transition/correction engine.
    for a in grupo:
        with con() as c:
            if etapa=="FOTO":
                v=personalizados.get(a["id"],"")
                c.execute("UPDATE anuncios SET link_foto=?,foto_override=? WHERE id=?",(v or campos["foto"],v or None,a["id"]))
            elif etapa=="VÍDEO":
                v=personalizados.get(a["id"],"")
                c.execute("UPDATE anuncios SET link_video=?,video_override=? WHERE id=?",(v or campos["video"],v or None,a["id"]))
            elif etapa=="PROMO":
                v=personalizados.get(a["id"],"")
                c.execute("UPDATE anuncios SET promo_override=? WHERE id=?",(v or None,a["id"]))
            elif etapa=="ADS":
                v=personalizados.get(a["id"],"")
                c.execute("UPDATE anuncios SET ads_override=? WHERE id=?",(v or None,a["id"]))
        er=finalizar(a["id"],user,campos)
        if er:return er
    return None

def trabalho(a,user):
    abrir(a["id"],user)
    with con() as c:
        a=c.execute("SELECT * FROM anuncios WHERE id=?",(a["id"],)).fetchone()
        p=c.execute("SELECT * FROM produtos WHERE sku=?",(a["sku"],)).fetchone()
    etapa=a["etapa"]
    grupo=anuncios_do_sku_na_etapa(a["sku"],etapa)
    # BASE remains independent per listing; correction also remains independent.
    agrupar=(etapa!="BASE" and a["status"]!="CORRIGIR" and len(grupo)>1)

    st.header(f"{'🔴 ' if a['prioridade']=='URGENTE' else '🟡 ' if a['prioridade']=='PRIORIDADE' else ''}{a['sku']} · {'SKU' if agrupar else 'Anúncio '+str(a['numero'])}")
    if agrupar:
        st.info(f"🧩 **{len(grupo)} anúncios vinculados neste SKU**. O dado informado abaixo será aplicado a todos por padrão.")
    else:
        st.caption(f"{etapa} · {a['responsavel'] or user['nome']} · em trabalho {age(a['inicio_etapa_em'])}")

    em_correcao=bool(a["correcao_retorno"] or a["correcao_origem"] or a["correcao_destino"])
    if em_correcao:
        st.error("🔴 CORREÇÃO SOLICITADA")
        st.write(f"**Solicitada por:** {a['correcao_origem'] or '—'}")
        st.write(f"**Motivo:** {a['correcao_motivo'] or 'Sem observação informada'}")
        st.info(f"Depois de finalizar, voltará automaticamente para **{a['correcao_retorno'] or a['correcao_origem']}**.")

    campos={}; personalizados={}
    if etapa=="BASE":
        campos["titulo"]=st.text_input("Título",a["titulo"] or "")
        campos["descricao"]=st.text_area("Descrição",a["descricao"] or "",height=180)
        campos["preco"]=st.number_input("Preço",0.0,value=float(a["preco"] or 0))
    elif etapa=="FOTO":
        campos["foto"]=st.text_input("Link da foto — padrão do SKU",p["foto_padrao"] or a["link_foto"] or "")
    elif etapa=="FÍSICA":
        campos["altura"]=st.number_input("Altura",0.0,value=float(p["altura"] or 0))
        campos["largura"]=st.number_input("Largura",0.0,value=float(p["largura"] or 0))
        campos["comprimento"]=st.number_input("Comprimento",0.0,value=float(p["comprimento"] or 0))
        campos["peso"]=st.number_input("Peso",0.0,value=float(p["peso"] or 0))
    elif etapa=="VÍDEO":
        campos["video"]=st.text_input("Link do vídeo — padrão do SKU",p["video_padrao"] or a["link_video"] or "")
    elif etapa=="PROMO":
        st.info("Confira a promoção dos anúncios vinculados e finalize quando estiver concluída.")
    else:
        st.info("Confira o ADS dos anúncios vinculados e finalize quando estiver concluído.")

    if agrupar and etapa in ["FOTO","VÍDEO"]:
        with st.expander("✏️ Personalizar algum anúncio"):
            st.caption("Deixe vazio para usar o dado padrão do SKU.")
            for x in grupo:
                atual=""
                if etapa=="FOTO": atual=x["foto_override"] or ""
                elif etapa=="VÍDEO": atual=x["video_override"] or ""
                elif etapa=="PROMO": atual=x["promo_override"] or ""
                elif etapa=="ADS": atual=x["ads_override"] or ""
                personalizados[x["id"]]=st.text_input(f"Anúncio {x['numero']} — {x['titulo'] or 'Sem título'}",atual,key=f"ov_{etapa}_{x['id']}")

    if agrupar:
        texto=f"✅ FINALIZAR {etapa} PARA OS {len(grupo)} ANÚNCIOS"
        if st.button(texto,type="primary",use_container_width=True):
            er=finalizar_grupo(a["sku"],etapa,user,campos,personalizados)
            if er:st.error(er)
            else:st.session_state.pop("aberto",None);st.rerun()
    else:
        texto_finalizar="✅ FINALIZAR CORREÇÃO" if em_correcao else f"✅ FINALIZAR {etapa}"
        if st.button(texto_finalizar,type="primary",use_container_width=True):
            er=finalizar(a["id"],user,campos)
            if er:st.error(er)
            else:st.session_state.pop("aberto",None);st.rerun()

    destinos=[e for e in ETAPAS if ETAPAS.index(e)<ETAPAS.index(etapa)]
    if destinos and not em_correcao:
        with st.expander("↩ Enviar para correção"):
            if agrupar:
                opcoes={f"Anúncio {x['numero']} — {x['titulo'] or 'Sem título'}":x["id"] for x in grupo}
                escolhidos=st.multiselect("Qual(is) anúncio(s) precisa(m) de correção?",list(opcoes.keys()))
                st.caption(f"SKU {a['sku']} possui {len(grupo)} anúncios nesta etapa. Selecione um, vários ou todos.")
            else:
                opcoes={f"Anúncio {a['numero']} — {a['titulo'] or 'Sem título'}":a["id"]}
                escolhidos=list(opcoes.keys())
            destino=st.selectbox("Enviar para qual etapa?",destinos)
            motivo=st.text_area("Motivo / observação da correção")
            if st.button("ENVIAR CORREÇÃO"):
                ids=[opcoes[x] for x in escolhidos]
                if not ids: st.error("Selecione pelo menos um anúncio.")
                elif not motivo.strip(): st.error("Informe o motivo da correção.")
                else:
                    for aid in ids: enviar_correcao(aid,user,destino,motivo)
                    st.session_state.pop("aberto",None);st.rerun()

init()

# login
if "uid" not in st.session_state:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:16px;margin:4px 0 8px 0;">
        <img src="data:image/png;base64,{logo_b64}" style="height:58px;width:auto;object-fit:contain;">
        <div style="font-size:2.45rem;font-weight:800;line-height:1;margin:0;">ESTEIRA ABX-ON</div>
    </div>
    """.format(logo_b64=logo_b64), unsafe_allow_html=True)
    st.caption("Acesso interno")
    with st.form("login"):
        login=st.text_input("Usuário");senha=st.text_input("Senha",type="password");go=st.form_submit_button("ENTRAR",type="primary",use_container_width=True)
    if go:
        with con() as c:u=c.execute("SELECT * FROM usuarios WHERE login=? AND senha=? AND ativo=1",(login,sh(senha))).fetchone()
        if u:st.session_state.uid=u["id"];st.rerun()
        else:st.error("Usuário ou senha inválidos.")
    st.info("""
**Acesso à Esteira ABX-ON**  
Utilize o usuário e a senha fornecidos pelo seu **gestor ou responsável**.  
Caso ainda não tenha acesso, solicite seu cadastro ao administrador do sistema.
""")
    st.stop()

with con() as c:user=c.execute("SELECT * FROM usuarios WHERE id=?",(st.session_state.uid,)).fetchone()
if not user or not user["ativo"]:st.session_state.clear();st.rerun()
ets=perms(user["id"]);adm=user["perfil"]=="ADMINISTRADOR";gest=user["perfil"] in ["ADMINISTRADOR","GESTOR"]
st.sidebar.write(f"**{user['nome']}**");st.sidebar.caption(user["perfil"])
if st.sidebar.button("Sair"):st.session_state.clear();st.rerun()
menu=["🏠 Meus Trabalhos","🔎 Buscar"]+(["📊 Gestão"] if gest else [])+(["⚙️ Administração","➕ Novo Produto"] if adm else [])
pag=st.sidebar.radio("Menu",menu)

if pag=="🏠 Meus Trabalhos":
    minhas=ETAPAS if adm else ets
    if not minhas:st.warning("O administrador ainda não atribuiu uma etapa ao seu acesso.");st.stop()
    if "aberto" in st.session_state:
        with con() as c:a= c.execute("SELECT * FROM anuncios WHERE id=?",(st.session_state.aberto,)).fetchone()
        if st.button("← Voltar"):st.session_state.pop("aberto");st.rerun()
        trabalho(a,user)
    else:
        st.header(f"Olá, {user['nome']} 👋")
        etapa=st.selectbox("Etapa",minhas) if len(minhas)>1 else minhas[0]
        rows=fila(etapa)
        # V6: pós-BASE, um SKU normal aparece como um trabalho; correções continuam individuais.
        if etapa!="BASE":
            vistos=set(); compact=[]
            for x in rows:
                chave=("CORR",x["id"]) if x["status"]=="CORRIGIR" else ("SKU",x["sku"])
                if chave not in vistos:
                    vistos.add(chave);compact.append(x)
            rows=compact
        hoje=datetime.now().strftime("%Y-%m-%d")
        with con() as c:feitos=c.execute("SELECT COUNT(*) n FROM historico WHERE acao='ETAPA CONCLUÍDA' AND observacao=? AND substr(data_hora,1,10)=?",(user["nome"],hoje)).fetchone()["n"]
        c1,c2,c3=st.columns(3);c1.metric("Para fazer",len(rows));c2.metric("Correções",sum(x["status"]=="CORRIGIR" for x in rows));c3.metric("Concluídos hoje",feitos)
        if rows and st.button("▶ ABRIR PRÓXIMO TRABALHO",type="primary",use_container_width=True):
            st.session_state.aberto=rows[0]["id"];st.rerun()
        for x in rows:
            ico="🔴" if x["prioridade"]=="URGENTE" else "🟡" if x["prioridade"]=="PRIORIDADE" else "⚪"
            with st.container(border=True):
                if etapa!="BASE" and x["status"]!="CORRIGIR":
                    with con() as c:nv=c.execute("SELECT COUNT(*) n FROM anuncios WHERE sku=? AND etapa=? AND status!='OK'",(x["sku"],etapa)).fetchone()["n"]
                    st.write(f"**{ico} {x['sku']} · 🧩 {nv} anúncio(s) vinculados**")
                else:
                    st.write(f"**{ico} {x['sku']} · Anúncio {x['numero']}**")
                st.caption(x["titulo"] or "Sem título")
                if x["status"]=="CORRIGIR":
                    st.error(f"🔴 CORREÇÃO SOLICITADA POR {x['correcao_origem'] or 'ETAPA ANTERIOR'}")
                    st.write(f"**Motivo:** {x['correcao_motivo'] or 'Sem observação informada'}")
                    st.caption(f"Aguardando correção há {age(x['entrada_etapa_em'])}")
                    rotulo="ABRIR CORREÇÃO"
                else:
                    st.caption(f"Na etapa há {age(x['entrada_etapa_em'])}")
                    rotulo="ABRIR"
                if st.button(rotulo,key=f"a{x['id']}"):st.session_state.aberto=x["id"];st.rerun()

elif pag=="📊 Gestão":
    st.header("📊 Painel Geral ABX-ON")
    with con() as c:
        ativos=c.execute("SELECT * FROM anuncios WHERE status!='OK'").fetchall()
        hoje=datetime.now().strftime("%Y-%m-%d")
        entraram=c.execute("SELECT COUNT(*) n FROM anuncios WHERE substr(criado_em,1,10)=?",(hoje,)).fetchone()["n"]
        finais=c.execute("SELECT COUNT(*) n FROM historico WHERE acao='ANÚNCIO FINALIZADO' AND substr(data_hora,1,10)=?",(hoje,)).fetchone()["n"]
        corrs=c.execute("SELECT COUNT(*) n FROM anuncios WHERE status='CORRIGIR'").fetchone()["n"]
    a,b,c=st.columns(3);a.metric("Entraram hoje",entraram);b.metric("Finalizados hoje",finais);c.metric("Em correção",corrs)
    cols=st.columns(6)
    for col,e in zip(cols,ETAPAS):
        n=sum(x["etapa"]==e for x in ativos);col.metric(e,n)
    st.subheader("Abrir uma etapa")
    e=st.selectbox("Etapa para inspecionar",ETAPAS)
    for x in fila(e):
        st.write(f"{x['prioridade']} · {x['sku']} / Anúncio {x['numero']} · {x['status']} · parado {age(x['entrada_etapa_em'])} · {x['responsavel'] or 'aguardando'}")

elif pag=="⚙️ Administração":
    st.header("⚙️ Administração")
    t1,t2=st.tabs(["👥 Equipe e Acessos","📜 Histórico Geral"])
    with t1:
        with st.form("novo"):
            nome=st.text_input("Nome");login=st.text_input("Login");senha=st.text_input("Senha inicial",type="password")
            perfil=st.selectbox("Perfil",PERFIS,index=2);pe=st.multiselect("Etapas",ETAPAS);ok=st.form_submit_button("CRIAR ACESSO",type="primary")
        if ok:
            try:
                if nome and login and senha:criar_user(nome,login,senha,perfil,pe);st.success("Criado.");st.rerun()
                else:st.error("Preencha nome, login e senha.")
            except sqlite3.IntegrityError:st.error("Login já existe.")
        with con() as c:us=c.execute("SELECT * FROM usuarios ORDER BY ativo DESC,nome").fetchall()
        for u in us:
            with st.expander(f"{'🟢' if u['ativo'] else '⚫'} {u['nome']} · {u['perfil']}"):
                n=st.text_input("Nome",u["nome"],key=f"n{u['id']}");pf=st.selectbox("Perfil",PERFIS,index=PERFIS.index(u["perfil"]),key=f"pf{u['id']}")
                at=st.checkbox("Ativo",bool(u["ativo"]),key=f"at{u['id']}");ee=st.multiselect("Etapas",ETAPAS,default=perms(u["id"]),key=f"e{u['id']}")
                ns=st.text_input("Nova senha",type="password",key=f"s{u['id']}")
                if st.button("SALVAR",key=f"sv{u['id']}"):update_user(u["id"],n,pf,at,ee,ns);st.rerun()
    with t2:
        with con() as c:h=c.execute("""SELECT h.data_hora,a.sku,a.numero,h.etapa,h.acao,h.observacao FROM historico h JOIN anuncios a ON a.id=h.anuncio_id ORDER BY h.id DESC LIMIT 2000""").fetchall()
        st.dataframe([dict(x) for x in h],use_container_width=True,hide_index=True)

elif pag=="➕ Novo Produto":
    st.header("➕ Novo Produto / Anúncios")
    sku=st.text_input("SKU").strip().upper();q=int(st.number_input("Quantidade de anúncios",1,20,3))
    prioridade=st.selectbox("Prioridade",PRIORIDADES,index=0);prazo=st.date_input("Prazo",value=None)
    ts=[];ds=[];ps=[]
    for j in range(q):
        with st.expander(f"Anúncio {j+1}",expanded=True):
            ts.append(st.text_input("Título",key=f"t{j}"));ds.append(st.text_area("Descrição",key=f"d{j}"));ps.append(st.number_input("Preço",0.0,key=f"p{j}"))
    if st.button("CRIAR E ENVIAR PARA BASE",type="primary",use_container_width=True):
        if sku:criar_anuncios(sku,q,ts,ds,ps,user,prioridade,str(prazo) if prazo else None);st.success("Criado.")
        else:st.error("Informe o SKU.")

else:
    q=st.text_input("Digite o SKU").strip().upper()
    if q:
        with con() as c:
            ans=c.execute("SELECT * FROM anuncios WHERE sku=? ORDER BY numero",(q,)).fetchall()
            hist=c.execute("""SELECT h.data_hora,h.etapa,h.acao,h.observacao FROM historico h JOIN anuncios a ON a.id=h.anuncio_id WHERE a.sku=? ORDER BY h.id DESC""",(q,)).fetchall()
        if not ans:st.warning("SKU não encontrado.")
        for x in ans:
            with st.container(border=True):
                st.write(f"**{x['sku']} · Anúncio {x['numero']}**")
                st.write(f"{x['prioridade']} · {x['etapa']} / {x['status']} · entrada {fmt(x['entrada_etapa_em'])}")
                st.caption(x["titulo"] or "Sem título")
                if x["status"]=="CORRIGIR":st.error(f"{x['correcao_destino']} precisa corrigir: {x['correcao_motivo']}")
        if hist:
            with st.expander("🕘 Linha do tempo completa",expanded=gest):
                st.dataframe([dict(x) for x in hist],use_container_width=True,hide_index=True)
