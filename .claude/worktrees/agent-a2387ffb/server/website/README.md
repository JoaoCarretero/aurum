# AURUM Finance — Website

Plataforma web do fundo quantitativo AURUM Finance.

## Estrutura

```
website/
├── public/
│   └── favicon.svg          # Logo Gold Ingot como favicon
├── src/
│   ├── components/
│   │   ├── Logo.jsx          # Gold Ingot logo (SVG)
│   │   ├── Globe.jsx         # Globo hermético animado
│   │   ├── Fade.jsx          # Animação scroll fade-in
│   │   └── Counter.jsx       # Contador animado
│   ├── utils/
│   │   └── data.js           # Dados demo + constantes de estratégia
│   ├── App.jsx               # App principal (Landing + Auth + Dashboard)
│   ├── theme.js              # Cores e tokens de design
│   ├── styles.css            # Estilos globais
│   └── main.jsx              # Entry point React
├── index.html
├── vite.config.js
├── package.json
└── README.md
```

## Setup (Windows)

1. Instalar Node.js 18+ em https://nodejs.org
2. Abrir terminal na pasta `website/`
3. Executar:

```bash
npm install
npm run dev
```

4. Abrir http://localhost:3000

## Build para produção

```bash
npm run build
```

Gera pasta `dist/` pronta para deploy em Vercel, Netlify ou qualquer host estático.

## Deploy rápido (Vercel)

1. Push para GitHub
2. Conectar repo no vercel.com
3. Deploy automático a cada push

## Próximos passos (backend)

Quando for integrar com backend real:
- Substituir dados demo em `src/utils/data.js` por chamadas API
- Adicionar Supabase para auth + banco de dados
- Integrar webhooks de depósito (crypto, PIX, Binance Pay)
- Conectar ao `session_*.json` do engine para dados reais de performance

## Tecnologias

- React 18 + Vite
- Recharts (gráficos)
- CSS puro (sem framework CSS)
- SVG para logo e globo
