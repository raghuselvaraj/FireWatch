"""FireWatch training pipeline.

Trains a DenseNet121 binary fire/no-fire classifier on the D-Fire dataset
using the same ``FireClassifier`` architecture the stream's classifier
backend uses, so the resulting checkpoint is drop-in compatible.

Entrypoints:
    python -m training.data.datasets --download
    python -m training.train --config training/configs/default.yaml
    python -m training.eval  --checkpoint training/runs/<id>/best.pt
    python -m training.export --checkpoint training/runs/<id>/best.pt
"""
