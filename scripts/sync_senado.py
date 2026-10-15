#!/usr/bin/env python3
"""
Coletor Oficial — Radar do Senado
Consome legis.senado.leg.br/dadosabertos e grava no banco PostgreSQL (Neon).
"""
import os
import time
import requests
import psycopg

BASE_URL = "https://legis.senado.leg.br/dadosabertos"
HEADERS = {"Accept": "application/json"}
DATABASE_URL = os.environ["DATABASE_URL"]


def get_json(path: str, params: dict = None) -> dict:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def ensure_list(val):
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def fetch_senadores_atuais():
    data = get_json("/senador/lista/atual")
    parlamentares = (
        data.get("ListaParlamentarEmExercicio", {})
        .get("Parlamentares", {})
        .get("Parlamentar", [])
    )
    return ensure_list(parlamentares)


def fetch_contagem_legislativa(codigo: int):
    # 1. Autorias do senador na legislatura atual
    autorias_count = 0
    try:
        aut_data = get_json(f"/senador/{codigo}/autorias", params={"tramitando": "S"})
        autorias = (
            aut_data.get("MateriasAutoriaParlamentar", {})
            .get("Parlamentar", {})
            .get("Autorias", {})
            .get("Autoria", [])
        )
        autorias_count = len(ensure_list(autorias))
    except Exception:
        pass

    # 2. Relatorias abertas/apresentadas
    relatorias_count = 0
    try:
        rel_data = get_json(f"/senador/{codigo}/relatorias")
        relatorias = (
            rel_data.get("MateriasRelatoriaParlamentar", {})
            .get("Parlamentar", {})
            .get("Relatorias", {})
            .get("Relatoria", [])
        )
        relatorias_count = len(ensure_list(relatorias))
    except Exception:
        pass

    # 3. Votações nominais registradas pelo senador
    participacao_pct = 0.0
    try:
        vot_data = get_json(f"/senador/{codigo}/votacoes")
        votacoes = (
            vot_data.get("VotacaoParlamentar", {})
            .get("Parlamentar", {})
            .get("Votacoes", {})
            .get("Votacao", [])
        )
        lista_vot = ensure_list(votacoes)
        if lista_vot:
            votos_efetivos = sum(
                1 for v in lista_vot
                if str(v.get("SiglaDescricaoVoto", "")).upper() in ("SIM", "NÃO", "NAO", "ABSTENÇÃO", "PRESIDENTE (ART. 51 RISF)")
            )
            participacao_pct = round((votos_efetivos / len(lista_vot)) * 100, 1)
    except Exception:
        pass

    return autorias_count, relatorias_count, participacao_pct


def sync():
    senadores = fetch_senadores_atuais()
    print(f"Encontrados {len(senadores)} senadores em exercicio na API do Senado.")

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for item in senadores:
                ident = item.get("IdentificacaoParlamentar", {})
                mandato = item.get("Mandato", {})

                codigo = int(ident["CodigoParlamentar"])
                nome = ident.get("NomeParlamentar", "")
                nome_completo = ident.get("NomeCompletoParlamentar", nome)
                partido = ident.get("SiglaPartidoParlamentar", "S/Partido")
                uf = ident.get("UfParlamentar", "DF")
                foto = ident.get("UrlFotoParlamentar", "")
                email = ident.get("EmailParlamentar", "")

                m_ini = int(mandato.get("PrimeiraLegislaturaDoMandato", {}).get("DataInicio", "2023")[:4])
                m_fim = int(mandato.get("SegundaLegislaturaDoMandato", {}).get("DataFim", "2031")[:4])

                autorias_count, relatorias_count, participacao_pct = fetch_contagem_legislativa(codigo)
                time.sleep(0.25)  # Respeita o rate-limit do Senado

                cur.execute(
                    """
                    INSERT INTO senadores (
                        codigo_parlamentar, nome_parlamentar, nome_completo,
                        sigla_partido, uf, url_foto, email_parlamentar,
                        mandato_inicio, mandato_fim, em_exercicio,
                        participacao_votos_pct, total_autorias, total_relatorias,
                        atualizado_em
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s, NOW()
                    )
                    ON CONFLICT (codigo_parlamentar) DO UPDATE SET
                        nome_parlamentar = EXCLUDED.nome_parlamentar,
                        sigla_partido = EXCLUDED.sigla_partido,
                        uf = EXCLUDED.uf,
                        url_foto = EXCLUDED.url_foto,
                        email_parlamentar = EXCLUDED.email_parlamentar,
                        participacao_votos_pct = EXCLUDED.participacao_votos_pct,
                        total_autorias = EXCLUDED.total_autorias,
                        total_relatorias = EXCLUDED.total_relatorias,
                        atualizado_em = NOW();
                    """,
                    (
                        codigo, nome, nome_completo, partido, uf, foto, email,
                        m_ini, m_fim, participacao_pct, autorias_count, relatorias_count
                    ),
                )
        conn.commit()
    print("Sincronizacao concluida com sucesso no Neon!")


if __name__ == "__main__":
    sync()
