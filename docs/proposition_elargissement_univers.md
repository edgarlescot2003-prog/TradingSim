# Proposition v3 — élargissement de l'univers d'actifs (Trading)

Version 3 du 25/09/2026, **validée par Edgar et intégrée le 26/09/2026**, après le second retour d'Edgar : **listes par zone, sans niveau pays**. Pour validation avant tout code : rien n'est poussé.
Niveaux : **constaté** (vérifié dans le code ou auprès de Yahoo/Kraken), **déduit**, **supposé**.

## 1. Ce qui change par rapport à la v2

- **Actions : une liste de 30 par zone** (Europe, Amérique, Asie), plus de liste par pays. Navigation : Accueil → Actions → **Zone** → liste (l'écran « Choisir un pays » disparaît). Le pays de chaque action reste affiché dans la colonne « Pays » de la liste.
- **Amérique = États-Unis + Canada regroupés** (choix fait pour Edgar, voir 3).
- **Matières premières : 3 familles** (Métaux, Énergie, Agriculture).
- Chine et Hong Kong : toujours exclus pour cette V1.
- Rappel (constaté) : la recherche reste indépendante des listes, n'importe quel ticker Yahoo/Kraken reste tradable.

## 2. Volumes

| Catégorie | Regroupement | Nombre |
|---|---|---|
| Actions — Europe | France 8 · Royaume-Uni 6 · Suisse 5 · Allemagne 4 · Espagne 4 · Italie 2 · Pays-Bas 1 | 30 |
| Actions — Amérique | États-Unis 25 · Canada 5 | 30 |
| Actions — Asie | Japon 17 · Inde 6 · Taïwan 5 · Corée du Sud 2 | 30 |
| Crypto | liste directe | 20 |
| Forex | 8 devises (EUR, USD, GBP, JPY, CHF, AUD, CAD, NZD) | 18 |
| Matières premières | Métaux 5 · Énergie 5 · Agriculture 6 | 16 |
| Obligations | 6 cartes | 16 |
| **Total** | | **160** |

## 3. Règle de sélection des actions (objective, vérifiable)

- **Les 30 plus grosses capitalisations de la zone**, données Yahoo du 25/09/2026 (constaté), converties en euros au change Yahoo du jour, parmi les grandes valeurs de chaque place (indices de référence). La répartition par pays **n'est pas imposée** : elle découle du classement.
- **Europe** : le classement pur couvre naturellement les 7 pays (tableau ci-dessus). Plus petite capitalisation retenue : ~109 Md€. Unilever, cotée à Londres ET Amsterdam, n'est gardée qu'une fois (Londres) : BNP Paribas entre en 30e position.
- **Amérique** : le classement pur ne retiendrait **que des actions américaines** (la 1re canadienne, Royal Bank of Canada, arrive 32e). Pour que la carte Amérique représente aussi le Canada, **25 américaines + les 5 plus grosses canadiennes**. C'est le seul ajustement manuel de la règle.
- **Asie** : Japon, Corée du Sud, Inde, **Taïwan** (plus besoin de choisir un pays : Taïwan entre par ses capitalisations, TSMC en tête). Samsung Biologics écartée (volume moyen < 100 000 titres/jour). Plus petite capitalisation retenue : ~69 Md€.

## 4. Indices affichés sur les cartes de zone (performance 2025, sources)

| Carte | Indices | Perf. 2025 | Sources |
|---|---|---|---|
| Europe | STOXX Europe 600 | ≈ +17 % | déjà en place (annexe B) |
| Amérique | S&P 500 · S&P/TSX Composite | +16,4 % · +28,2 % | déjà en place (annexe B) |
| Asie | Nikkei 225 | +26,2 % | déjà en place (annexe B) |
| Asie | KOSPI | **+75,6 %** | [Korea Herald](https://www.koreaherald.com/article/10646103) (clôture 4 214,17 contre 2 399) ; [Korea JoongAng Daily](https://www.koreajoongangdaily.com/business/kospi-outperforms-all-other-major-global-indexes-in-2025-as-non-us-markets-overshadow-sp/11952226) |
| Asie | Nifty 50 | **+10,5 %** (10,51 %) | [Samco](https://www.samco.in/knowledge-center/articles/nifty-gains-10-51-and-nifty-bank-rises-17-15-in-calendar-year-2025/) (clôture 26 129,60) ; [Business Standard](https://www.business-standard.com/amp/markets/news/nifty-climbs-0-8pc-sensex-adds-600-pts-on-cy25-finale-why-stock-markets-are-rising-today-125123100443_1.html) |
| Asie | TAIEX | **+25,7 %** (25,73 %) | [Focus Taiwan](https://focustaiwan.tw/business/202512310018) (clôture 28 963,60) ; [Taipei Times](https://www.taipeitimes.com/News/front/archives/2026/01/01/2003849853) |

Hang Seng et Shanghai Composite sont retirés de la carte Asie (Chine exclue). IBEX 35 (+49,3 %) et FTSE MIB (+31,4 %), trouvés pour la v2, ne sont plus nécessaires sans cartes pays (conservés en commentaire dans la configuration pour une V2 éventuelle).

## 5. Conséquences techniques

- **Plus besoin des contours** Espagne, Italie, Corée, Inde (pas de cartes pays) ; seule la **Nouvelle-Zélande** est à générer (carte NZD du Forex).
- **Cron** : ~160 requêtes espacées ≈ **5 à 6 minutes** par nuit (au lieu de ~15). Les 3 passages validés (2h17, 4h17, 6h17 à Paris l'été) gardent une très large marge.
- **Filet de secours** : la plus grande liste fait 30 actifs → au pire ~30 requêtes espacées sur ~60 s depuis l'IP de Streamlit, un seul chargement à la fois, prix affichés au fur et à mesure (validé).
- **Corrections préalables validées, toujours nécessaires** : pence/cents (6 actions de Londres ⚠ + 5 contrats agricoles), secours limité à la liste affichée, correspondances Kraken et fonds obligataires.
- L'écran « Choisir un pays », la carte large « Toute la zone » et les indices par pays deviennent inutiles : retirés de la navigation (configuration conservée en commentaire).

## 6. Rien d'autre à trancher

Sauf remarque d'Edgar sur la liste ci-dessous, j'enchaîne dans cet ordre, avec un push par lot : (1) correction pence/cents + correspondances Kraken/obligations, (2) secours limité à la liste + cron dédié, (3) nouvel univers + navigation par zone + familles/cartes Forex, Obligations, Matières premières.

## 7. Liste détaillée des actions (vérifiée auprès de Yahoo le 25/09/2026)

⚠ = cotation en pence (`GBp`) : nécessite la correction pence/cents avant intégration. Crypto, Forex, Matières premières et Obligations : inchangés depuis la v2 (voir 8).

### Actions — Europe (30)

Répartition : France 8, Royaume-Uni 6, Suisse 5, Allemagne 4, Espagne 4, Italie 2, Pays-Bas 1

| # | Ticker | Nom (Yahoo) | Pays | Devise | Capitalisation (Md€) |
|---|---|---|---|---|---|
| 1 | `ASML.AS` | ASML Holding N.V. | Pays-Bas | EUR | 585 |
| 2 | `RO.SW` | Roche Holding AG | Suisse | CHF | 317 |
| 3 | `HSBA.L` | HSBC Holdings plc | Royaume-Uni | GBp ⚠ | 301 |
| 4 | `NOVN.SW` | Novartis AG | Suisse | CHF | 241 |
| 5 | `SHEL.L` | Shell plc | Royaume-Uni | GBp ⚠ | 239 |
| 6 | `AZN.L` | AstraZeneca PLC | Royaume-Uni | GBp ⚠ | 226 |
| 7 | `SIE.DE` | Siemens Aktiengesellschaft | Allemagne | EUR | 217 |
| 8 | `SAP.DE` | SAP SE | Allemagne | EUR | 215 |
| 9 | `NESN.SW` | Nestlé S.A. | Suisse | CHF | 210 |
| 10 | `OR.PA` | L'Oréal S.A. | France | EUR | 203 |
| 11 | `MC.PA` | LVMH Moët Hennessy - Louis Vuitton, Société Européenne | France | EUR | 196 |
| 12 | `SAN.MC` | Banco Santander, S.A. | Espagne | EUR | 182 |
| 13 | `TTE.PA` | TotalEnergies SE | France | EUR | 177 |
| 14 | `ITX.MC` | Industria de Diseño Textil, S.A. | Espagne | EUR | 166 |
| 15 | `SU.PA` | Schneider Electric S.E. | France | EUR | 164 |
| 16 | `ALV.DE` | Allianz SE | Allemagne | EUR | 161 |
| 17 | `ABBN.SW` | ABB Ltd | Suisse | CHF | 154 |
| 18 | `AIR.PA` | Airbus SE | France | EUR | 152 |
| 19 | `RR.L` | Rolls-Royce Holdings plc | Royaume-Uni | GBp ⚠ | 142 |
| 20 | `RMS.PA` | Hermès International Société en commandite par actions | France | EUR | 141 |
| 21 | `SAF.PA` | Safran SA | France | EUR | 139 |
| 22 | `BBVA.MC` | Banco Bilbao Vizcaya Argentaria, S.A. | Espagne | EUR | 139 |
| 23 | `IBE.MC` | Iberdrola, S.A. | Espagne | EUR | 136 |
| 24 | `RIO.L` | Rio Tinto Group | Royaume-Uni | GBp ⚠ | 134 |
| 25 | `UBSG.SW` | UBS Group AG | Suisse | CHF | 132 |
| 26 | `DTE.DE` | Deutsche Telekom AG | Allemagne | EUR | 129 |
| 27 | `UCG.MI` | UniCredit S.p.A. | Italie | EUR | 127 |
| 28 | `ISP.MI` | Intesa Sanpaolo S.p.A. | Italie | EUR | 118 |
| 29 | `ULVR.L` | Unilever PLC | Royaume-Uni | GBp ⚠ | 117 |
| 30 | `BNP.PA` | BNP Paribas SA | France | EUR | 109 |

### Actions — Amérique (30)

Répartition : États-Unis 25, Canada 5

| # | Ticker | Nom (Yahoo) | Pays | Devise | Capitalisation (Md€) |
|---|---|---|---|---|---|
| 1 | `NVDA` | NVIDIA Corporation | États-Unis | USD | 4,771 |
| 2 | `AAPL` | Apple Inc. | États-Unis | USD | 4,369 |
| 3 | `GOOGL` | Alphabet Inc. | États-Unis | USD | 3,692 |
| 4 | `MSFT` | Microsoft Corporation | États-Unis | USD | 3,364 |
| 5 | `AMZN` | Amazon.com, Inc. | États-Unis | USD | 2,364 |
| 6 | `META` | Meta Platforms, Inc. | États-Unis | USD | 1,681 |
| 7 | `AVGO` | Broadcom Inc. | États-Unis | USD | 1,478 |
| 8 | `TSLA` | Tesla, Inc. | États-Unis | USD | 1,290 |
| 9 | `BRK-B` | Berkshire Hathaway Inc. | États-Unis | USD | 950 |
| 10 | `LLY` | Eli Lilly and Company | États-Unis | USD | 926 |
| 11 | `AMD` | Advanced Micro Devices, Inc. | États-Unis | USD | 904 |
| 12 | `JPM` | JPMorgan Chase & Co. | États-Unis | USD | 800 |
| 13 | `WMT` | Walmart Inc. | États-Unis | USD | 752 |
| 14 | `V` | Visa Inc. | États-Unis | USD | 605 |
| 15 | `XOM` | ExxonMobil Holdings Corporation | États-Unis | USD | 580 |
| 16 | `JNJ` | Johnson & Johnson | États-Unis | USD | 574 |
| 17 | `INTC` | Intel Corporation | États-Unis | USD | 571 |
| 18 | `MA` | Mastercard Incorporated | États-Unis | USD | 437 |
| 19 | `ABBV` | AbbVie Inc. | États-Unis | USD | 410 |
| 20 | `CSCO` | Cisco Systems, Inc. | États-Unis | USD | 369 |
| 21 | `ORCL` | Oracle Corporation | États-Unis | USD | 364 |
| 22 | `COST` | Costco Wholesale Corporation | États-Unis | USD | 359 |
| 23 | `CVX` | Chevron Corporation | États-Unis | USD | 352 |
| 24 | `BAC` | Bank of America Corporation | États-Unis | USD | 348 |
| 25 | `KO` | The Coca-Cola Company | États-Unis | USD | 332 |
| 26 | `RY.TO` | Royal Bank of Canada | Canada | CAD | 245 |
| 27 | `TD.TO` | The Toronto-Dominion Bank | Canada | CAD | 174 |
| 28 | `SHOP.TO` | Shopify Inc. | Canada | CAD | 161 |
| 29 | `BMO.TO` | Bank of Montreal | Canada | CAD | 105 |
| 30 | `BNS.TO` | The Bank of Nova Scotia | Canada | CAD | 100 |

### Actions — Asie (30)

Répartition : Japon 17, Inde 6, Taïwan 5, Corée du Sud 2

| # | Ticker | Nom (Yahoo) | Pays | Devise | Capitalisation (Md€) |
|---|---|---|---|---|---|
| 1 | `2330.TW` | Taiwan Semiconductor Manufacturing Company Limited | Taïwan | TWD | 1,775 |
| 2 | `005930.KS` | Samsung Electronics Co., Ltd. | Corée du Sud | KRW | 1,213 |
| 3 | `000660.KS` | SK hynix Inc. | Corée du Sud | KRW | 855 |
| 4 | `2454.TW` | MediaTek Inc. | Taïwan | TWD | 233 |
| 5 | `8306.T` | Mitsubishi UFJ Financial Group, Inc. | Japon | JPY | 233 |
| 6 | `7203.T` | Toyota Motor Corporation | Japon | JPY | 198 |
| 7 | `9984.T` | SoftBank Group Corp. | Japon | JPY | 196 |
| 8 | `RELIANCE.NS` | Reliance Industries Limited | Inde | INR | 152 |
| 9 | `8316.T` | Sumitomo Mitsui Financial Group, Inc. | Japon | JPY | 147 |
| 10 | `8035.T` | Tokyo Electron Limited | Japon | JPY | 143 |
| 11 | `6501.T` | Hitachi, Ltd. | Japon | JPY | 138 |
| 12 | `2308.TW` | Delta Electronics, Inc. | Taïwan | TWD | 137 |
| 13 | `6098.T` | Recruit Holdings Co., Ltd. | Japon | JPY | 127 |
| 14 | `6758.T` | Sony Group Corporation | Japon | JPY | 121 |
| 15 | `9983.T` | Fast Retailing Co., Ltd. | Japon | JPY | 118 |
| 16 | `8411.T` | Mizuho Financial Group, Inc. | Japon | JPY | 117 |
| 17 | `6861.T` | Keyence Corporation | Japon | JPY | 108 |
| 18 | `HDFCBANK.NS` | HDFC Bank Limited | Inde | INR | 104 |
| 19 | `BHARTIARTL.NS` | Bharti Airtel Limited | Inde | INR | 102 |
| 20 | `3711.TW` | ASE Technology Holding Co., Ltd. | Taïwan | TWD | 101 |
| 21 | `8058.T` | Mitsubishi Corporation | Japon | JPY | 99 |
| 22 | `2317.TW` | Hon Hai Precision Industry Co., Ltd. | Taïwan | TWD | 97 |
| 23 | `ICICIBANK.NS` | ICICI Bank Limited | Inde | INR | 87 |
| 24 | `8001.T` | ITOCHU Corporation | Japon | JPY | 86 |
| 25 | `8766.T` | Tokio Marine Holdings, Inc. | Japon | JPY | 85 |
| 26 | `SBIN.NS` | State Bank of India | Inde | INR | 83 |
| 27 | `6981.T` | Murata Manufacturing Co., Ltd. | Japon | JPY | 81 |
| 28 | `9432.T` | NTT, Inc. | Japon | JPY | 80 |
| 29 | `7011.T` | Mitsubishi Heavy Industries, Ltd. | Japon | JPY | 73 |
| 30 | `TCS.NS` | Tata Consultancy Services Limited | Inde | INR | 69 |

## 8. Autres catégories (Matières premières en 3 familles : Métaux = précieux + cuivre)
### Crypto

#### Liste directe (20)

| Ticker | Nom (Yahoo) | Devise |
|---|---|---|
| `BTC-USD` | Bitcoin USD | USD |
| `ETH-USD` | Ethereum USD | USD |
| `SOL-USD` | Solana USD | USD |
| `XRP-USD` | XRP USD | USD |
| `ADA-USD` | Cardano USD | USD |
| `DOGE-USD` | Dogecoin USD | USD |
| `TRX-USD` | TRON USD | USD |
| `AVAX-USD` | Avalanche USD | USD |
| `LINK-USD` | Chainlink USD | USD |
| `DOT-USD` | Polkadot USD | USD |
| `LTC-USD` | Litecoin USD | USD |
| `BCH-USD` | Bitcoin Cash USD | USD |
| `XLM-USD` | Stellar USD | USD |
| `UNI7083-USD` | Uniswap | USD |
| `ATOM-USD` | Cosmos USD | USD |
| `NEAR-USD` | NEAR Protocol USD | USD |
| `AAVE-USD` | Aave USD | USD |
| `ETC-USD` | Ethereum Classic USD | USD |
| `FIL-USD` | Filecoin USD | USD |
| `ALGO-USD` | Algorand USD | USD |

### Forex (regroupé par devise : EUR, USD, GBP, JPY, CHF, AUD, CAD, NZD)

#### Paires (18)

| Ticker | Nom (Yahoo) | Devise |
|---|---|---|
| `EURUSD=X` | EUR/USD | USD |
| `GBPUSD=X` | GBP/USD | USD |
| `USDJPY=X` | USD/JPY | JPY |
| `USDCHF=X` | USD/CHF | CHF |
| `AUDUSD=X` | AUD/USD | USD |
| `USDCAD=X` | USD/CAD | CAD |
| `NZDUSD=X` | NZD/USD | USD |
| `EURGBP=X` | EUR/GBP | GBP |
| `EURJPY=X` | EUR/JPY | JPY |
| `EURCHF=X` | EUR/CHF | CHF |
| `GBPJPY=X` | GBP/JPY | JPY |
| `AUDJPY=X` | AUD/JPY | JPY |
| `EURAUD=X` | EUR/AUD | AUD |
| `GBPCHF=X` | GBP/CHF | CHF |
| `CHFJPY=X` | CHF/JPY | JPY |
| `EURCAD=X` | EUR/CAD | CAD |
| `CADJPY=X` | CAD/JPY | JPY |
| `AUDNZD=X` | AUD/NZD | NZD |

### Matières premières (3 familles)

#### Métaux précieux (4)

| Ticker | Nom (Yahoo) | Devise |
|---|---|---|
| `GC=F` | Gold Dec 26 | USD |
| `SI=F` | Silver Dec 26 | USD |
| `PL=F` | Platinum Oct 26 | USD |
| `PA=F` | Palladium Dec 26 | USD |

#### Métaux (suite) : cuivre (1)

| Ticker | Nom (Yahoo) | Devise |
|---|---|---|
| `HG=F` | Copper Dec 26 | USD |

#### Énergie (5)

| Ticker | Nom (Yahoo) | Devise |
|---|---|---|
| `CL=F` | Crude Oil Nov 26 | USD |
| `BZ=F` | Brent Crude Oil Last Day Financial Futures | USD |
| `NG=F` | Natural Gas Nov 26 | USD |
| `RB=F` | RBOB Gasoline Nov 26 | USD |
| `HO=F` | Heating Oil Nov 26 | USD |

#### Agriculture (6)

| Ticker | Nom (Yahoo) | Devise |
|---|---|---|
| `ZC=F` | Corn Futures,Dec-2026 | USX ⚠ |
| `ZW=F` | Chicago SRW Wheat Futures,Dec-2 | USX ⚠ |
| `ZS=F` | Soybean Futures,Nov-2026 | USX ⚠ |
| `KC=F` | Coffee Dec 26 | USX ⚠ |
| `SB=F` | Sugar #11 Oct 26 | USX ⚠ |
| `CC=F` | Cocoa Dec 26 | USD |

### Obligations (6 cartes)

#### Court terme (2)

| Ticker | Nom (Yahoo) | Devise |
|---|---|---|
| `SGOV` | iShares 0-3 Month Treasury Bond ETF | USD |
| `SHY` | iShares 1-3 Year Treasury Bond ETF | USD |

#### Moyen terme (2)

| Ticker | Nom (Yahoo) | Devise |
|---|---|---|
| `IEI` | iShares 3-7 Year Treasury Bond ETF | USD |
| `IEF` | iShares 7-10 Year Treasury Bond ETF | USD |

#### Long terme (2)

| Ticker | Nom (Yahoo) | Devise |
|---|---|---|
| `TLH` | iShares 10-20 Year Treasury Bond ETF | USD |
| `TLT` | iShares 20+ Year Treasury Bond ETF | USD |

#### Diversifiés (4)

| Ticker | Nom (Yahoo) | Devise |
|---|---|---|
| `GOVT` | iShares U.S. Treasury Bond ETF | USD |
| `BND` | Vanguard Total Bond Market Index Fund ETF Shares | USD |
| `AGG` | iShares Core U.S. Aggregate Bond ETF | USD |
| `MUB` | iShares National Muni Bond ETF | USD |

#### Entreprises (3)

| Ticker | Nom (Yahoo) | Devise |
|---|---|---|
| `LQD` | iShares iBoxx $ Investment Grade Corporate Bond ETF | USD |
| `HYG` | iShares iBoxx $ High Yield Corporate Bond ETF | USD |
| `JNK` | State Street SPDR Bloomberg High Yield Bond ETF | USD |

#### Inflation & international (3)

| Ticker | Nom (Yahoo) | Devise |
|---|---|---|
| `TIP` | iShares TIPS Bond ETF | USD |
| `BNDX` | Vanguard Total International Bond Index Fund ETF Shares | USD |
| `EMB` | iShares J.P. Morgan USD Emerging Markets Bond ETF | USD |
