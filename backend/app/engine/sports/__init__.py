"""Motor de deportes (Fase 6, docs/PLATAFORMA_COMPLETA.md §8.4 y §8.5).

Python puro, con la misma disciplina que el resto de `engine/`: sin FastAPI, sin
SQLAlchemy, sin red. En la etapa 1 solo sirve al backtest fuera de muestra; nada
de lo que calcula se muestra al cliente hasta que un deporte pase ese backtest.

- `odds`: probabilidad implicita de una cuota y como quitarle el margen.
- `events`: el partido, generico sobre resultados (con o sin empate).
- `models`: una estimacion estadistica propia por deporte.
- `recommendation`: "Apostar: ..." solo si la cuota paga mas que la estimacion.
- `backtest`: walk-forward por temporadas y el veredicto de §8.5.
"""
