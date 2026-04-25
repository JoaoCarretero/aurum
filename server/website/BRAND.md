# AURUM — Brand & Design System (Website)

> Estado atual do site (`server/website/`) — não é uma proposta, é o que existe.
> Atualizar este arquivo a cada mudança visual. Single source of truth para
> componentes, tokens e padrões do front institucional.

---

## Stack real

- **React 18 + Vite 5** (módulo único, sem framework UI, sem Tailwind)
- **framer-motion 12.38** — usado em Hero (eyebrow/título/lede/cta) e Terminal.
  Reveal, StatusTicker e os orbs do Hero foram **migrados para CSS / IO nativo**
  para evitar o crash `mixers[i] is not a function` que travava o rAF loop
  quando `transition.ease` recebia um objeto em vez de bezier array
  (ver `lib/tokens.js` e a seção "Bug fixes 2026-04-25" abaixo)
- **recharts 2** — único gráfico atualmente é a `EquityCurve`
- Sem TypeScript, sem build de CSS — `src/styles.css` é um arquivo único global
- Fonts via Google Fonts (`@import` no topo de `styles.css`)
- Build alvo: `vite build` → `dist/` estático (Vercel/Netlify ready)

---

## Paleta — Half-Life 2 / Source Engine VGUI

A paleta **não** é "preto + dourado puro" como a primeira leitura do
mockup pode sugerir. É charcoal industrial + amber HL2 + cream warm.
Importada 1:1 de `core/ui/ui_palette.py` (a paleta do launcher TkInter).

### Backgrounds (charcoal)

| Token CSS | Token JS (`tokens.js`) | Hex/RGBA               | Uso                |
| --------- | ---------------------- | ---------------------- | ------------------ |
| `--bg`    | `bg`                   | `#2A2A2A` / `#1B1B1B`* | body principal     |
| `--bg2`   | `bg2`                  | `#333333` / `#242424`* | tab inativo        |
| `--bg3`   | `bg3`                  | `#3A3A3A` / `#2A2A2A`* | painel / card      |
| `--bg4`   | `bg4`                  | `#4C4C4C` / `#333333`* | hover surface      |
| `--bg5`   | `bg5`                  | `#565656` / `#4C4C4C`* | botão              |

*\* divergência conhecida: `styles.css` (`--bg`) e `tokens.js` (`bg`) estão
com hexes ligeiramente diferentes. Item de cleanup futuro — não causa
bug visível porque cada lado só usa "seu" token.*

### Borders

| CSS                  | JS              | Valor                          |
| -------------------- | --------------- | ------------------------------ |
| `--brd`              | `brd`           | `rgba(214,201,154,0.09)`       |
| `--brd2`             | `brdStrong`     | `rgba(214,201,154,0.18)`       |
| `--brd-gold`         | `brdAmber`      | `rgba(208,143,54,0.32)`        |
| `--brd-gold-strong`  | `brdAmberStrong`| `rgba(208,143,54,0.55)`        |

### Texto — warm cream

| CSS              | JS             | Hex         | Uso                                  |
| ---------------- | -------------- | ----------- | ------------------------------------ |
| `--t`            | `t`            | `#D6C99A`   | corpo padrão                         |
| `--t2`           | `t2`           | `#B0A17F`   | corpo dim / lede                     |
| `--t3`           | `t3`           | `#8F8F8F`   | metadado                             |
| `--t4`           | `t4`           | `#6A6A6A`   | quiet (caption, footer)              |
| `--silver`       | `silver`       | `#D6C99A`   | alias de `--t` (paridade JS↔CSS)     |
| `--silverBright` | `silverBright` | `#EDE0B1`   | títulos hero/section, highlight      |

### Amber (acento principal — HL2 orange)

| CSS                | JS            | Hex/RGBA                  |
| ------------------ | ------------- | ------------------------- |
| `--gold`           | `amber`       | `#D08F36`                 |
| `--goldBright`     | `amberBright` | `#F0A847`                 |
| `--goldDim`        | `amberDim`    | `#8F7A45`                 |
| `--goldBg`         | `amberBg`     | `rgba(208,143,54,0.08)`   |
| `--goldBgStrong`   | `amberBgStrong`| `rgba(208,143,54,0.18)`  |
| `--goldGlow`       | `amberGlow`   | `rgba(208,143,54,0.35–0.42)` |

> **Drift histórico:** o sistema CSS chama de `--gold*` o que o sistema JS
> chama de `amber*`. Ambos coexistem; padronizar exige refactor de ~30
> arquivos. Não foi feito.

### Status (HL2 HUD)

| CSS         | JS         | Hex          | Significado            |
| ----------- | ---------- | ------------ | ---------------------- |
| `--g`       | `good`     | `#7FA84A`    | edge real, ok          |
| `--g-bg`    | `goodBg`   | rgba 12%     |                        |
| `--g-glow`  | `goodGlow` | rgba 35–38%  |                        |
| `--r`       | `bad`      | `#C44535`    | dano, falha            |
| `--r-bg`    | `badBg`    | rgba 12%     |                        |
| `--w`       | `warn`     | `#E8C87A`    | aviso (edge moderado)  |
| `--w-bg`    | `warnBg`   | rgba 10%     |                        |
| `--cyan`    | `cyan`     | `#7FA0B0`    | steel pipe (raro)      |

---

## Tipografia

```css
--f:  'Inter',           system-ui, sans-serif;       /* body / UI */
--fd: 'Instrument Serif', Georgia, serif;             /* display / títulos */
--fm: 'Geist Mono',     'JetBrains Mono', ui-monospace, monospace;
```

Carregadas via `@import` Google Fonts no topo de `src/styles.css`. Pesos
importados (após cleanup): **Inter 400/500/600**, **Geist Mono 300/400/500/600**,
**Instrument Serif 400** (com itálico). Inter 700 foi removido (não usava ninguém).

> **Não** usar Cormorant Garamond / Outfit / Space Grotesk / Inter sozinho.
> A combinação **Instrument Serif itálico para o gold accent** é a
> assinatura visual — toda `<em>` dentro de `.section__title`,
> `.bento__title`, `.pillar__title` herda essa cor.

### Escala efetivamente usada

- `body { font-size: 13.5px; line-height: 1.55; }` — base apertada
- `.hero__title` — `clamp(36px, 6vw, 72px)`, line-height 1.02
- `.section__title` — `clamp(28px, 3.6vw, 48px)`
- `.bento__title` — `clamp(18px, 1.7vw, 24px)`
- `.principle__title`, `.research-card__title` — 18px
- Eyebrows / tags / chips — 9–11px com letter-spacing 0.14–0.20em
- Mono em métricas: 17–22px, `font-variant-numeric: tabular-nums`

---

## Princípios de design

1. **Estética**: institucional, alquímica, sofisticada — Renaissance/Citadel
   meets Source Engine VGUI. Industrial, não luxuoso.
2. **Paleta restrita**: charcoal + amber + cream + verde/vermelho de status.
   Nada de roxo, ciano vivo, gradientes "rainbow" de iridescência.
3. **Movimento**: institucional, sem bounce. Easing custom `[0.16, 1, 0.3, 1]`
   exposto via `tokens.ease` — usado tanto pelo CSS (na transição da
   `.reveal`) quanto pelos motion components que sobraram (Hero text,
   Terminal). `tokens.ease` agora é um **bezier array direto**, não um
   objeto — passar objeto crashava framer-motion 12.
4. **Densidade controlada**: bastante texto, mas hierarquia clara.
   Eyebrow uppercase mono → título serif → corpo Inter.
5. **Honestidade visual**: cards de performance reportam `EDGE_MODERADO`
   ao lado de `EDGE_REAL`. Nenhum brilho excessivo. O graveyard é
   metodologia.
6. **Acessibilidade**: `prefers-reduced-motion` respeitado globalmente
   no fim de `styles.css`. `.reveal` e `.iridescent` ambos têm overrides
   explícitos para reduced-motion. `aria-label` no nav, `role="status"`
   no ticker, `aria-hidden` nos layers decorativos do `IridescentCard`.

---

## Componentes

### Layout / shell
- `components/Nav.jsx` (`.nav`, `.nav--scrolled`) — fixed top, blur ao scroll
- `components/StatusTicker.jsx` (`.ticker`) — marquee fixo de 26px no topo,
  **CSS `@keyframes tickerScroll` puro** (sem framer-motion)
- `components/Footer.jsx` (`.footer`) — grid 4 colunas, disclaimer
- `components/Logo.jsx` — chevron "A" SVG com gradiente HL2 + glow filter

### Primitivas
- `components/Reveal.jsx` — wrapper de scroll-fade-in **nativo**
  (IntersectionObserver + CSS transition, sem framer). API:
  `{ children, delay = 0, y = 12, className, as = "div" }`. Plumba
  `delay` (segundos→ms) e `y` via CSS variables `--reveal-delay` / `--reveal-y`.
- `components/Metric.jsx` — number counter animado com `useSpring` do
  framer-motion. Funciona porque agora `ease` é bezier array válido.
- `components/Terminal.jsx` (`.terminal`) — fake terminal animado no hero
  (framer-motion para entrada + interval para line-by-line).
- `components/charts/EquityCurve.jsx` — Recharts area chart usando
  `tokens.amberBright` / `tokens.amber` (era `tokens.silverBright` →
  undefined, curva invisível).
- `components/IridescentCard.jsx` — wrapper para cards premium com
  cursor-tracked sheen/glow/edge/noise + tilt 3D no hover. Paleta
  restrita amber + cream. Detalhes na seção "IridescentCard" abaixo.

### Sections (todas em `src/sections/`)

| Arquivo            | ID              | § | Conteúdo                                            |
| ------------------ | --------------- | - | --------------------------------------------------- |
| `Hero.jsx`         | `#top`          |   | Eyebrow + título + lede + CTAs + métricas + Terminal. Orbs decorativos estáticos (parallax `useScroll` removido). |
| `Bento.jsx`        | `#platform`     | II| 5 cards assimétricos (signal, risk, OOS, pipeline, sovereignty) |
| `Thesis.jsx`       | `#thesis`       | I | Lede + 3 pillars                                    |
| `Methodology.jsx`  | `#methodology`  |III| Protocol (5 itens) + Graveyard (5 engines)          |
| `Performance.jsx`  | `#performance`  | IV| 3 engine-cards (CITADEL lead + JUMP + RENAISSANCE) **wrapped em IridescentCard** + tabela cross-engine |
| `CodeShowcase.jsx` | `#code`         | V | 3 code-cards (signal/risk/sizing) com syntax highlight hand-rolled |
| `Technology.jsx`   | `#technology`   | VI| Engine stack (5 rows) + pipeline 10-step           |
| `Principles.jsx`   | `#principles`   |VII| 7 cards numerados (I–VII)                           |
| `Research.jsx`     | `#research`     |VIII| 4 research-cards (Audit/Methodology/Framework/Risk) |
| `Contact.jsx`      | `#contact`      | IX| Form mailto: + email link                           |

### Tokens / dados
- `lib/tokens.js` — paleta + fonts + ease (bezier array) + easeInOut + easeSmooth
- `lib/data.js` — `SITE`, `ENGINES`, `ARCHIVED`, `ANTI_OVERFIT`, `PRINCIPLES`, `RESEARCH`, `curve()` (gerador synthetic equity)

---

## IridescentCard

Wrapper de premium card com efeito metálico amber reativo ao cursor.
**Paleta restrita amber + cream** — sem rainbow oil-slick.

### API
```jsx
<IridescentCard className="engine-card engine-card--lead">
  ...children intactos do engine-card original...
</IridescentCard>
```
Aceita props: `children`, `className` (mergeada com `iridescent`), `as`
(default `"article"`), e qualquer prop adicional via `...rest`.

### O que faz
- `pointermove` → escreve `--mx`, `--my`, `--rx`, `--ry`, `--ang` no
  elemento dentro de um único `requestAnimationFrame` com auto-stop
  quando o lerp converge.
- 4 camadas decorativas (todas `pointer-events: none`, `aria-hidden`):
  - `.iridescent__sheen` — conic-gradient amber/cream rotacionando com `--ang`
  - `.iridescent__glow` — radial-gradient amber especular sob o cursor
  - `.iridescent__edge` — radial-gradient cream com mask para iluminar
    só o pedaço da borda 1px mais perto do cursor
  - `.iridescent__noise` — turbulence SVG inline (filme grain)
- Idle: sem transform 3D (evita compositing edge-cases).
- Hover: `perspective(1100px) rotateX/Y(±5°/±7°) translateY(-3px)` +
  border amber + box-shadow com glow.
- `prefers-reduced-motion`: zero JS (matchMedia early-return) e camadas
  forçadas a `opacity: 0`.
- `(hover: none)` (touch): camadas `display: none`, transform desligado.

### Onde está aplicado
- 3 engine-cards de `Performance.jsx` (CITADEL/JUMP/RENAISSANCE).

### Como adicionar em outras cards
1. Importar: `import { IridescentCard } from "../components/IridescentCard";`
2. Substituir `<article className="X">` por `<IridescentCard className="X">`
   (e `</article>` por `</IridescentCard>`).
3. Os filhos devem ter background contrastante (cards charcoal funcionam).
   Se a base for transparente, o sheen vira invisível — adicione
   background sólido na class.
4. CSS já tem `.iridescent.engine-card:hover` específico. Para outras
   classes, criar um override análogo se quiser combinar com `translateY`.

---

## Bug fixes 2026-04-25

Esta sessão corrigiu uma cadeia de bugs preexistentes que surgiram
quando o framer-motion 12.38 aplicou validação mais estrita de easing.

### 1. `tokens.js: ease` era objeto, não bezier
`export const ease = { out, inOut, smooth }`. Todos os consumers passavam
o objeto inteiro como `transition.ease`. framer-motion 12 não reconhecia
o formato, retornava o objeto, e tentava chamá-lo como função no mixer
chain → `Uncaught TypeError: a is not a function` no rAF tick → loop
morria → todas as `Reveal` `whileInView` paravam → sections invisíveis
em `opacity: 0`.

**Fix:** `export const ease = [0.16, 1, 0.3, 1]` direto, com `easeInOut`
e `easeSmooth` como named exports separados.

### 2. `EquityCurve` usava tokens inexistentes
`tokens.silverBright` e `tokens.silver` não existiam em `tokens.js` →
stroke/fill da curva da CITADEL eram `undefined` → invisível em produção.

**Fix:** trocados por `tokens.amberBright` / `tokens.amber`. Aliases
`silver` / `silverBright` adicionados ao `tokens` para futuras paridade
com o CSS.

### 3. `StatusTicker` `animate={{ x: ["0%", "-50%"] }}` causava parser issues
Combinação de keyframes percentage com transform `x` em framer 12
era um second-stage trigger.

**Fix:** marquee migrado para `@keyframes tickerScroll` CSS puro.

### 4. Hero `useScroll` warning
`useScroll({ target: ref, offset: [...] })` aplicado em `.hero` produzia
warning sobre container position e potencialmente NaN no progresso.

**Fix:** parallax dos orbs removido, orbs agora estáticos. Os
`motion.div` de eyebrow/title/lede/cta continuam com `ease` correto.

---

## Convenções deste repo

- Comentários em **inglês** no código React (alinhado com o resto do site)
- Documentação `.md` em **português** quando voltada ao Joao
- Snippets de uso vão neste arquivo, não em READMEs separados
- Cada componente novo: documentar tokens consumidos + estados visuais
- `framer-motion` é frágil em 12.x — preferir CSS quando possível
  (tickers, fade-ins, hover effects). Reservar framer para count-ups
  (`useSpring`) e entradas que precisam de delay-chain encadeada.
