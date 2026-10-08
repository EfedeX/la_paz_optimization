# 💧 La Paz Proactiva

**Datos y modelos para que el agua de La Paz, BCS se gestione de forma preventiva y no solo reaccionando.**

Este es un prototipo abierto y apartidista. Muestra cómo un organismo operador como OOMSAPAS
podría anticipar fallas en pozos, pronosticar la demanda y repartir mejor el agua disponible,
usando herramientas de código abierto y de bajo costo.

| Módulo | Pregunta | Datos |
|---|---|---|
| 1 · Alerta temprana de pozos | ¿Qué pozo va a fallar y con cuántos días de aviso? | 🧪 Telemetría simulada con fallas inyectadas |
| 2 · Demanda de agua | ¿Cuánta agua necesitará cada sector en 14 días? | 🧪 Simulada, calibrada con población y clima |
| 3 · Tandeo optimizado | ¿Cómo repartir de forma más justa el agua que sí hay? | Capacidad pública + programación lineal |
| 4 · Mapa | ¿Dónde está el déficit y qué pozos están en riesgo? | Sectores aproximados |
| 5 · Transparencia OOMSAPAS | ¿Qué publica el organismo y en qué gasta? | 📊 Plataforma Nacional de Transparencia |

## Resultados del prototipo (con datos simulados)

- **Detección:** 9 de 9 fallas inyectadas detectadas. En las fallas graduales, el aviso llega
  con **~17 días de anticipación** (mediana) y la tasa de falsas alarmas es de ~0.1% de los
  días-pozo sanos.
- **Demanda:** error de 3.7% (MAPE) pronosticando con 14 días de anticipación, contra 6.6%
  de suponer que se repetirá lo de hace dos semanas.
- **Tandeo:** con la misma agua, la cobertura del sector peor atendido sube unos 15 puntos.
  El modelo también señala qué sectores no alcanzan el mínimo por falta de conexión, que es
  donde conviene invertir en obra.

> ⚠️ **Lo que es real y lo que no.** OOMSAPAS no publica telemetría de bombas ni tiene
> micromedición, así que los módulos 1 y 2 usan datos **simulados**. Las fallas simuladas son
> más fáciles de detectar que las reales, y los umbrales se tendrán que recalibrar con datos
> reales. Las cifras públicas usadas son:
> - 70 pozos y ~300 l/hab/día (director de OOMSAPAS, 2026);
> - 716.4 + 343.3 l/s de capacidad (Tercer Informe 2024);
> - ~40% de pérdidas por fugas (exdirector de OOMSAPAS).
>
> La población por sector es una **aproximación** al Censo 2020 y hay que reemplazarla con las
> AGEB del INEGI.

## Cómo correrlo

```bash
pip install -r requirements.txt
streamlit run Inicio.py
pytest -q
```

## Scraper de la Plataforma Nacional de Transparencia

La consulta pública de la PNT para OOMSAPAS La Paz (entidad 3, sujeto obligado 782) es difícil
de navegar. El scraper no depende de una API documentada: abre la página con Playwright, hace
clic en cada obligación, registra las peticiones JSON que hace el sitio y descarga los formatos.
Después repite esas peticiones paginando y guarda todo en tablas limpias.

```bash
python -m playwright install chromium        # solo la primera vez, en tu máquina
PYTHONPATH=src python -m lapaz.pnt discover --ejercicio 2024 2025 2026   # --headed para ver el navegador
PYTHONPATH=src python -m lapaz.pnt scrape    # pagina los endpoints descubiertos → data/pnt/tablas/*.parquet
PYTHONPATH=src python -m lapaz.pnt report    # data/pnt/hallazgos.md
# ¿Ya bajaste los XLSX a mano desde la PNT? Normalízalos:
PYTHONPATH=src python -m lapaz.pnt ingest ~/Descargas/pnt
```

- El scraper hace 1 petición por segundo, se identifica con un User-Agent y solo descarga
  información pública.
- Clasifica contratos y gastos en pozos y bombas, pipas, energía, redes y fugas, medición,
  potabilización y drenaje.
- La página 5 del dashboard también acepta los XLSX subidos directamente.
- **No se pudo probar contra la PNT real:** el entorno de desarrollo bloqueaba el dominio.
  La lógica de normalización, categorización y paginación tiene pruebas con datos de ejemplo
  en formato SIPOT. Es posible que haya que ajustar los selectores la primera vez que se
  corra contra el sitio.

## Estructura

```
Inicio.py, pages/          Dashboard (Streamlit)
src/lapaz/data/            Datos públicos (public.py) y simulador de pozos (simulate.py)
src/lapaz/models/          anomaly.py (z robusto, CUSUM, Isolation Forest) · demand.py (Gradient Boosting)
src/lapaz/optimize/        tandeo.py (programación lineal en dos etapas, HiGHS)
src/lapaz/pnt/             Scraper/normalizador de la PNT
data/sample/               Sectores aproximados (para correr sin internet)
tests/                     pytest
```

## Siguiente fase

1. **Datos reales:** pedir por transparencia las bitácoras de bombeo, los recibos de CFE por
   pozo y el tandeo vigente (la lista completa está en la página 5). Con kWh y horas de bombeo
   ya se puede estimar la eficiencia de cada bomba.
2. **Piloto:** instalar caudalímetro y manómetro con registro horario en 5 pozos críticos y
   conectarlos al módulo 1.
3. **Vialidad:** mapa de baches a partir de reportes ciudadanos y fotos, priorización de
   bacheo por tráfico, y sincronización de semáforos en los corredores principales.
4. **DENUE:** estimar la demanda comercial (hoteles, purificadoras, lavanderías) con
   `fetch_denue()`, que requiere `INEGI_TOKEN`.
