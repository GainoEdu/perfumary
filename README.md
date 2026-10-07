# Loja de Perfumes (Flask + PostgreSQL) — pronta para o Render

Python 3.12 · Flask · SQLAlchemy · Flask-Migrate · PostgreSQL · HTML/CSS/JS puros.

## DEPLOY NO RENDER

1. **Suba para o GitHub**: crie um repositório e envie *o conteúdo desta pasta* (o arquivo `render.yaml` precisa ficar na raiz do repositório).
2. No Render: **New → Blueprint** → escolha o repositório → **Apply**.
3. Aguarde o deploy (o Render cria o site e o banco PostgreSQL sozinho).
4. Abra `https://SEU-SITE.onrender.com/admin/login`.
   - E-mail: `admin@minhaloja.com` (ou o valor de `ADMIN_EMAIL`)
   - Senha: no Render, abra o serviço → **Environment** → `ADMIN_PASSWORD` (gerada automaticamente).
5. Em **Admin → Conta**, troque o e-mail e a senha. Pronto: o resto é tudo pelo painel.

### O que acontece sozinho no start
`python manage.py init_db` espera o banco ficar disponível, roda as migrations, cria os dados de demonstração (uma única vez) e cria o administrador se ainda não existir (nunca sobrescreve). Depois o Gunicorn sobe o site.

## O que você configura pelo painel (`/admin`)
Produtos (ml livre, notas olfativas, preço, promoção, estoque, galeria de imagens), marcas, categorias, famílias olfativas, pedidos, clientes, banners, página inicial (seções liga/desliga), aparência (cores, logo, favicon), configurações (contato, redes, rodapé, frete).

## Decisões técnicas
- **Sem Docker**: o ambiente Python nativo do Render é o caminho mais simples e confiável aqui.
- **Imagens ficam no PostgreSQL** (o disco do Render é efêmero): zero configuração e nada se perde em deploys. Todo upload é validado e re-codificado (Pillow).
- **Segurança**: CSRF, CSP/headers, hash de senha (Werkzeug), rate limit, cookies seguros, checagem de admin no servidor em *todas* as rotas `/admin/*`, preço e estoque sempre lidos/atualizados no banco em transação.
- **Pagamento**: não há cartão. O pedido nasce "Aguardando pagamento". Para integrar um gateway, implemente `app/payments.py`.

## Planos gratuitos do Render
O banco **free expira em ~30 dias** e o site free "dorme" sem tráfego. Para produção real, troque `plan` em `render.yaml` por um plano pago antes do deploy (ou depois, no painel do Render).

## Desenvolvimento local (opcional)
```
pip install -r requirements-dev.txt
pytest
```
