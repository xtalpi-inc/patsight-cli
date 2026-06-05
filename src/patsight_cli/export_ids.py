from __future__ import annotations

from typing import Any, Dict, List, Optional


def compound_rows_to_export_ids(compounds: List[Dict[str, Any]]) -> List[Dict[str, Optional[int]]]:
    """Map ``/compounds`` rows to export ``ids`` payload items."""
    ids: List[Dict[str, Optional[int]]] = []
    for compound in compounds:
        structure_id = compound.get("id")
        property_id = compound.get("property_id")
        if structure_id is None and property_id is None:
            continue
        entry: Dict[str, Optional[int]] = {}
        if property_id is not None:
            entry["property_id"] = int(property_id)
        if structure_id is not None:
            entry["structure_id"] = int(structure_id)
        ids.append(entry)
    return ids
