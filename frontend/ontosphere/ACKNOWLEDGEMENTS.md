Acknowledgements
================

Ontosphere builds on several open-source projects and libraries whose authors
we gratefully acknowledge.

## Core components

| Component | Authors / Maintainers | Role in Ontosphere |
|-----------|----------------------|-------------------|
| [Konclude](https://github.com/konclude/Konclude) | [Andreas Steigmiller](https://github.com/andreas-steigmiller), Thorsten Liebig, Birte Glimm (Institute of Artificial Intelligence, University of Ulm) | OWL 2 DL tableau reasoner (SROIQ(D)), compiled to WebAssembly via [rdf-reasoner-konclude](https://github.com/ThHanke/rdf-reasoner-konclude). All credit for the reasoning algorithm belongs to Andreas Steigmiller |
| [Reactodia](https://github.com/reactodia/reactodia-workspace) | Dmitry Mouromtsev et al. | Visual graph editor — canvas, authoring, halo, entity search |
| [N3.js](https://github.com/rdfjs/N3.js) | Ruben Verborgh, Ruben Taelman | In-memory RDF store, Turtle/N-Triples/N3 parser and serializer |
| [shacl-engine](https://github.com/zazuko/shacl-engine) | Thomas Bergwinkl | SHACL constraint validation engine |

> Steigmiller, A., Liebig, T., & Glimm, B. (2014). _Konclude: System Description._
> Journal of Web Semantics, 27–28, 78–85. doi:10.1016/j.websem.2014.06.003

## Layout and graph algorithms

| Component | Role |
|-----------|------|
| [ELK (elkjs)](https://github.com/kieler/elkjs) | Layered, force, stress, and radial graph layout algorithms |
| [Dagre](https://github.com/dagrejs/dagre) | Directed graph layout (horizontal / vertical) |
| [ngraph.louvain](https://github.com/nickolay/ngraph.louvain) / [ngraph.slpa](https://github.com/nickolay/ngraph.slpa) | Community detection for hierarchical clustering (Louvain, Label Propagation) |
| [ml-kmeans](https://github.com/mljs/kmeans) | K-Means clustering |

## RDF and SPARQL

| Component | Role |
|-----------|------|
| [@rdfjs/data-model](https://github.com/rdfjs-base/data-model) / [@rdfjs/dataset](https://github.com/rdfjs-base/dataset) | RDF/JS data model and dataset interfaces |
| [rdf-parse](https://github.com/rubensworks/rdf-parse.js) | Multi-format RDF parser (Turtle, JSON-LD, RDF/XML, N-Triples) |
| [sparqljs](https://github.com/RubenVerborgh/SPARQL.js) | SPARQL query parser |
| [Comunica](https://github.com/comunica/comunica) | SPARQL query engine over RDF/JS sources |

## UI framework

| Component | Role |
|-----------|------|
| [React](https://react.dev) | UI rendering |
| [Radix UI](https://www.radix-ui.com) | Accessible, unstyled UI primitives |
| [Tailwind CSS](https://tailwindcss.com) | Utility-first CSS framework |
| [Vite](https://vite.dev) | Build tool and dev server |
| [Lucide](https://lucide.dev) | Icon set |
| [shadcn/ui](https://ui.shadcn.com) | Component patterns built on Radix + Tailwind |

## Institutional support

This work was supported by the
[Fraunhofer Institute for Mechanics of Materials IWM](https://www.iwm.fraunhofer.de/).
