"""Everything a Discord user can *do* through the bot, as opposed to read.

``actions`` is the fixed list of platform calls a button may make, ``cards``
lays notification cards (and replies) out as Components V2, ``copy`` holds the
reply wording, and ``dispatcher`` runs one action for the person who clicked.
``/mix`` is another entry point into the same dispatcher: the identity rule
and the action list do not change with the surface.
"""
