"""app.ingestion.ifc: a model's quantities per item number, read from the STEP file."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors import InvalidInputError
from app.ingestion.ifc import read_takeoff
from app.models.model_takeoff import code_key, same_text

# IFC2X3 in millimetres: two pipe segments linked to 1.1 (one states both net and gross
# length), a valve linked to 1.2, a slab linked to both 1.3 and 1.4, and an unlinked wall.
MODEL = b"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('m.ifc','2026-11-21T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('IFC2X3'));
ENDSEC;
DATA;
/* a comment with #99=IFCWALL( inside */
#1=IFCPROJECT('0p',$,'Ringschluss \\X2\\00DC\\X0\\berleitung',$,$,$,$,$,#2);
#2=IFCUNITASSIGNMENT((#3,#4,#5));
#3=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
#4=IFCSIUNIT(*,.AREAUNIT.,.MILLI.,.SQUARE_METRE.);
#5=IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.);
#10=IFCPIPESEGMENT('a1',$,'Pipe ''A''',$,$,$,$,$);
#11=IFCPIPESEGMENT('a2',$,'Pipe B',$,$,$,$,$);
#12=IFCVALVE('v1',$,'Valve',$,$,$,$,$);
#13=IFCSLAB('s1',$,'Slab',$,$,$,$,$,$);
#14=IFCWALL('w1',$,'Wall',$,$,$,$,$);
#20=IFCQUANTITYLENGTH('GrossLength',$,$,12500.,$);
#21=IFCQUANTITYLENGTH('Length',$,$,12000.,$);
#22=IFCQUANTITYLENGTH('Width',$,$,400.,$);
#23=IFCELEMENTQUANTITY('q1',$,'Qto',$,$,(#20,#21,#22));
#24=IFCQUANTITYLENGTH('Length',$,$,3E3,$);
#25=IFCELEMENTQUANTITY('q2',$,'Qto',$,$,(#24));
#26=IFCQUANTITYAREA('GrossArea',$,$,2.5E7,$);
#27=IFCQUANTITYVOLUME('NetVolume',$,$,IFCVOLUMEMEASURE(5.),$);
#28=IFCELEMENTQUANTITY('q3',$,'Qto',$,$,(#26,#27));
#30=IFCRELDEFINESBYPROPERTIES('r1',$,$,$,(#10),#23);
#31=IFCRELDEFINESBYPROPERTIES('r2',$,$,$,(#11),#25);
#32=IFCRELDEFINESBYPROPERTIES('r3',$,$,$,(#13,#14),#28);
#40=IFCCLASSIFICATION('GAEB',$,$,'LV');
#41=IFCCLASSIFICATIONREFERENCE($,'01.0001','Rohr PE 63',#40);
#42=IFCCLASSIFICATIONREFERENCE($,'1.2',$,#40);
#43=IFCCLASSIFICATIONREFERENCE($,'1.3',$,#40);
#44=IFCCLASSIFICATIONREFERENCE($,'1.4',$,#40);
#50=IFCRELASSOCIATESCLASSIFICATION('c1',$,$,$,(#10,#11),#41);
#51=IFCRELASSOCIATESCLASSIFICATION('c2',$,$,$,(#12),#42);
#52=IFCRELASSOCIATESCLASSIFICATION('c3',$,$,$,(#13),#43);
#53=IFCRELASSOCIATESCLASSIFICATION('c4',$,$,$,(#13),#44);
ENDSEC;
END-ISO-10303-21;
"""


def test_quantities_are_summed_per_item_number_in_base_units() -> None:
    takeoff = read_takeoff(MODEL, filename="m.ifc")
    assert (takeoff.schema, takeoff.project) == ("IFC2X3", "Ringschluss Überleitung")
    assert (takeoff.elements, takeoff.unlinked_elements) == (5, 1)
    pipe = takeoff.positions["01.0001"]
    # Net or plain length before gross; never a width. Millimetres become metres.
    assert pipe.quantities == {"length": Decimal("15"), "count": Decimal(2)}
    assert (pipe.global_ids, pipe.names) == (("a1", "a2"), ("Pipe 'A'", "Pipe B"))
    assert pipe.reference_name == "Rohr PE 63"
    # Pieces are counted as elements; an element without quantities still counts.
    assert takeoff.positions["1.2"].quantities == {"count": Decimal(1)}
    # mm² to m²; the volume unit has no prefix; a typed value is read.
    slab = takeoff.positions["1.3"].quantities
    assert slab == {"area": Decimal("25"), "volume": Decimal("5"), "count": Decimal(1)}
    assert takeoff.positions["1.4"].quantities == slab  # one element, two positions


def test_a_dimension_is_summed_only_when_every_element_states_it() -> None:
    model = MODEL.replace(b"#31=IFCRELDEFINESBYPROPERTIES('r2',$,$,$,(#11),#25);\n", b"")
    assert "length" not in read_takeoff(model, filename="m.ifc").positions["01.0001"].quantities


@pytest.mark.parametrize(
    "data",
    [b"PK\x03\x04 not a model", b"ISO-10303-21;\nHEADER;FILE_SCHEMA(('AP214'));ENDSEC;DATA;"],
)
def test_other_files_are_refused(data: bytes) -> None:
    with pytest.raises(InvalidInputError):
        read_takeoff(data, filename="x.ifc")


def test_item_numbers_and_short_texts_are_compared_leniently() -> None:
    assert code_key("03.02.0009") == code_key("3.2.9") == code_key("03 02 0009")
    assert code_key("TEL00009") != code_key("08.01.0003")
    assert same_text("Rasen  ansäen Parkplatzrasen", "rasen ansäen parkplatzrasen")
    cut = "Kies-Sand-Gemisch Einbettung Rohr DN300-400 einbauen verdich"
    assert same_text(cut, cut + "ten D 30cm")  # cut off at a field width
    assert not same_text("Bordstein", "Bordstein Beton abbrechen")  # too short to be cut off
