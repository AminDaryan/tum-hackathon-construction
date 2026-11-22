# GAEB DA XML schemas

Official XML schemas of GAEB DA XML, unchanged. Only the exchange phases the workbench reads are
bundled: X81, X83, X84, X86, and the files they redefine or import. The files carry no licence
text unless noted; they are bundled so validation works offline.
`app/ingestion/gaeb/schemas.py` pins each file by SHA-256 and refuses a changed file.

## 3.3 (release 2021-05)

- Source: <https://www.gaeb.de/wp-content/uploads/2021/06/2021-05_Leistungsverzeichnis.zip>
  (Gemeinsamer Ausschuss Elektronik im Bauwesen, public download; retrieved 2026-11-19, X86
  2026-11-20).

| File | SHA-256 |
| --- | --- |
| GAEB_DA_XML_81_3.3_2021-05.xsd | aa24ed698088308d38f1ff7612643e55e70a847f6b5d433aa10dcd6dfe6c3ea3 |
| GAEB_DA_XML_83_3.3_2021-05.xsd | a963ca5b6a93ee0f7a83d3138272a4116635e30e7b288c6ba8761ed444cabaa8 |
| GAEB_DA_XML_84_3.3_2021-05.xsd | 67282b688db3bb12a4ded22c7b677e30ce105f9d1f80d02d084be67156e1cc42 |
| GAEB_DA_XML_86_3.3_2021-05.xsd | 334853ca68fe07c1321880c40f27b776c8133ec8c34207c63b0d438ab6e45e0d |
| GAEB_DA_XML_Lib_3.3_2021-05.xsd | a00cad3a5bfaf079de936393c0827c2387d4b9407c113359cca4b493903388ec |

## 3.2 (release 2013-10)

- Source: <https://www.gaeb.de/wp-content/uploads/2019/04/Leistungsverzeichnis.zip>
  (retrieved 2026-11-20).

| File | SHA-256 |
| --- | --- |
| GAEB_DA_XML_81_3.2_2013-10.xsd | 655f8a49716efd7186f6598c29b5208032060f57bc7f251c68d895ff0a7213f5 |
| GAEB_DA_XML_83_3.2_2013-10.xsd | 51bcd0cc37c7851dbb89520d8a6663b9fcaa9982575476410432e346132c8f6e |
| GAEB_DA_XML_84_3.2_2013-10.xsd | c57677b3b8be38371dabc9a83781049be483f0bd99eb9b771851ea9a6959ea5e |
| GAEB_DA_XML_86_3.2_2013-10.xsd | 41e4da0a21f4164e625d867f5c0dc5a5c49be3075689668ee3e364b95cf75706 |
| GAEB_DA_XML_Lib_3.2_2013-10.xsd | f8d736e96f3f2e1ba6e97aa0492dedad1c2064fafc502a7f70466b34b67d1f77 |

## 3.1 (release 2009-12)

One schema covers X81 to X83 and X85 to X87; X84 has its own. Both import the two W3C schemas,
which are shipped in the same downloads (`xmldsig-core-schema.xsd` is under the W3C Software
License, stated in the file).

- Sources: <https://www.gaeb.de/wp-content/uploads/2022/11/Schema_GAEB_DA_XML_3.1_2009-12_X81-X83_u_X85-X87.zip>
  and <https://www.gaeb.de/wp-content/uploads/2022/11/Schema_GAEB_DA_XML_3.1_2009-12_X84.zip>
  (retrieved 2026-11-20).

| File | SHA-256 |
| --- | --- |
| GAEB_DA_XML 3.1 2009-12.xsd | 4baa2b88e489ca9797ad63e8e6ee5af6fd2d93a312bd9b9a8b6ad660a48438c3 |
| GAEB_DA_XML_84 3.1 2009-12.xsd | f26d50c58c478fd7599c2a1f87a5d30451dce538ced3a4292c05e4e4200611de |
| xml.xsd | 068d7ed95badc1ccf1be78b47e97a3ad9f7d10e17d3d3d684606e62a85de20ed |
| xmldsig-core-schema.xsd | af234e51dee3dbc3be288c79abdca95208e228f400259c8a485099bfb75eb88f |

To support another version or phase, add its files here and one entry in `schemas.py`.
