// api/senadores.js — Serverless Endpoint com Cache em CDN (Edge)
import { neon } from '@neondatabase/serverless';

export default async function handler(req, res) {
  try {
    const sql = neon(process.env.DATABASE_URL);
    const senadores = await sql`
      SELECT *
      FROM vw_painel_senadores
      ORDER BY presenca_plenario_pct DESC, participacao_votos_pct DESC
    `;

    // Cache de 1 hora na CDN (s-maxage=3600) para suportar picos de tráfego
    res.setHeader('Cache-Control', 'public, s-maxage=3600, stale-while-revalidate=86400');
    return res.status(200).json({
      atualizado_em: new Date().toISOString(),
      total: senadores.length,
      senadores
    });
  } catch (error) {
    return res.status(500).json({ error: 'Erro ao consultar dados no Neon' });
  }
}
