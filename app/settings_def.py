"""Tudo que o administrador edita pelo painel (sem mexer em código)."""

# chave: (rótulo, tipo, valor padrão, ajuda)
FIELDS = {
    "store_name": ("Nome da loja", "text", "Maison Parfum", ""),
    "store_tagline": ("Slogan", "text", "Perfumes que contam histórias", ""),
    "logo_media": ("Logo", "image", "", "PNG com fundo transparente fica melhor."),
    "favicon_media": ("Favicon", "image", "", "Imagem quadrada (PNG)."),
    "store_email": ("E-mail da loja", "email", "", ""),
    "whatsapp": ("WhatsApp (somente números, com DDD)", "text", "", "Ex.: 19999998888"),
    "phone": ("Telefone", "text", "", ""),
    "address": ("Endereço", "text", "", ""),
    "instagram": ("Instagram (URL)", "url", "", ""),
    "facebook": ("Facebook (URL)", "url", "", ""),
    "tiktok": ("TikTok (URL)", "url", "", ""),
    "opening_hours": ("Horário de funcionamento", "textarea", "Seg a Sex, 9h às 18h", ""),
    "footer_text": ("Texto do rodapé", "textarea", "Fragrâncias selecionadas com cuidado.", ""),
    "shipping_flat": ("Frete fixo (R$)", "money", "25.00", ""),
    "free_shipping_above": ("Frete grátis acima de (R$)", "money", "299.00", "0 desativa o frete grátis."),
    "seo_description": ("Descrição para o Google", "textarea", "Perfumes nacionais e importados com entrega para todo o Brasil.", ""),
    # aparência
    "color_primary": ("Cor principal (dourado)", "color", "#b8923a", ""),
    "color_secondary": ("Cor secundária", "color", "#111111", ""),
    "color_button": ("Cor dos botões", "color", "#111111", ""),
    "color_button_text": ("Cor do texto dos botões", "color", "#ffffff", ""),
    "color_bg": ("Cor do fundo", "color", "#faf6ef", ""),
    "color_text": ("Cor dos textos", "color", "#1b1b1b", ""),
    # página inicial
    "hero_title": ("Título do banner principal", "text", "A arte de se perfumar", ""),
    "hero_subtitle": ("Subtítulo", "text", "Descubra fragrâncias nacionais e importadas selecionadas para você.", ""),
    "hero_button_text": ("Texto do botão", "text", "Ver perfumes", ""),
    "hero_link": ("Link do botão", "text", "/produtos", "Ex.: /produtos ou https://..."),
    "hero_image": ("Imagem do banner principal", "image", "", "Recomendado: 1600x700."),
    "show_banners": ("Mostrar banners promocionais", "bool", "1", ""),
    "show_featured": ("Mostrar produtos em destaque", "bool", "1", ""),
    "show_bestsellers": ("Mostrar mais vendidos", "bool", "1", ""),
    "show_offers": ("Mostrar ofertas", "bool", "1", ""),
    "show_new": ("Mostrar novidades", "bool", "1", ""),
    "show_brands": ("Mostrar marcas", "bool", "1", ""),
    "show_categories": ("Mostrar categorias", "bool", "1", ""),
    "title_featured": ("Título: destaques", "text", "Em destaque", ""),
    "title_bestsellers": ("Título: mais vendidos", "text", "Mais vendidos", ""),
    "title_offers": ("Título: ofertas", "text", "Ofertas", ""),
    "title_new": ("Título: novidades", "text", "Novidades", ""),
    "title_brands": ("Título: marcas", "text", "Nossas marcas", ""),
    "title_categories": ("Título: categorias", "text", "Explore por categoria", ""),
}

MAXLEN = {"text": 200, "email": 255, "url": 300, "textarea": 1000}

GROUPS = {
    "store": [
        ("Identidade", ["store_name", "store_tagline", "seo_description"]),
        ("Contato", ["store_email", "whatsapp", "phone", "address", "opening_hours"]),
        ("Redes sociais", ["instagram", "facebook", "tiktok"]),
        ("Rodapé", ["footer_text"]),
        ("Frete", ["shipping_flat", "free_shipping_above"]),
    ],
    "appearance": [
        ("Logo e ícone", ["logo_media", "favicon_media"]),
        ("Cores", ["color_primary", "color_secondary", "color_button", "color_button_text", "color_bg", "color_text"]),
    ],
    "homepage": [
        ("Loja", ["store_name", "logo_media"]),
        ("Banner principal", ["hero_title", "hero_subtitle", "hero_button_text", "hero_link", "hero_image"]),
        ("Seções (ativar/desativar)", ["show_banners", "show_featured", "show_bestsellers", "show_offers", "show_new", "show_brands", "show_categories"]),
        ("Títulos das seções", ["title_featured", "title_bestsellers", "title_offers", "title_new", "title_brands", "title_categories"]),
    ],
}
