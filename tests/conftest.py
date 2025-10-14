class FakeSerial:
    """Simulierte Serial-Schnittstelle für Tests."""

    def __init__(self, responses: dict):
        """
        responses: dict mapping block_name -> bytes
        """
        self._responses = responses
        self.read_count = {key: 0 for key in responses}

    def write(self, data: bytes):
        """Schreibt Daten. Wird nur gezählt, kein Effekt."""
        pass

    def read(self, n: int) -> bytes:
        """
        Simuliert ein Lesevorgang. Gibt die nächsten n Bytes zurück.
        Hier werden einfach die kompletten Bytes des Blocks zurückgegeben.
        """
        # Optional: Erweiterung um Sequenznummern oder Lese-Counter
        # Für Tests reicht einfaches Zurückgeben
        raise NotImplementedError("Direktes Lesen über FakeSerial nicht unterstützt. Verwende read_block_by_name.")

    def read_block_by_name(self, block_name: str) -> bytes:
        """Gibt die vordefinierten Bytes für den Block zurück und zählt den Zugriff."""
        if block_name not in self._responses:
            raise KeyError(f"Block {block_name} nicht definiert in FakeSerial")
        self.read_count[block_name] += 1
        return self._responses[block_name]