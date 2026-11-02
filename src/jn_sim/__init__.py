"""jn_sim — event-vision closed-loop simulator for the jetson_neuro project.

The package is split so that the *shared modules* — ``__init__``, ``__main__``,
``ctl``, ``link``, ``protocol``, ``provenance`` and ``testctl`` — import only
the standard library and numpy, and run unchanged on the Jetson's Python 3.12
(spec R1.3). The simulator-only modules (plant, renderer, event model, loop,
viewer, host adapter) are imported lazily by the ``run`` subcommand.
"""

__version__ = "0.1.0"
