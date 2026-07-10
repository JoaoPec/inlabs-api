"""Parse do XML de artigo do DOU → dict no MESMO formato que o Apps Script consome.

Campos de saída (contrato com o Apps Script):
  source, externalId, fileName, title, subtitle, ementa, orgao,
  textoResumo, link, publishedAt, publishedIso, secao, editionDate
(+ extras inofensivos: pubName, artType)
"""
import html
import re
import xml.etree.ElementTree as ET


def _norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_html(text):
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text or "", flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return _norm(text)


def _local(tag):
    return tag.split("}")[-1].lower()


def _find_article(root):
    if _local(root.tag) == "article":
        return root
    for el in root.iter():
        if _local(el.tag) == "article":
            return el
    return root


def _el_by_names(article, names):
    wanted = {n.lower() for n in names}
    for el in article.iter():
        if _local(el.tag) in wanted:
            return el
    return None


def _text_by_names(article, names):
    el = _el_by_names(article, names)
    if el is None:
        return ""
    return _norm("".join(el.itertext()))


def _parse_date(raw, edition_date):
    for source in (raw, edition_date):
        s = (source or "").strip()
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
        if m:
            return "%s-%s-%sT00:00:00" % (m.group(3), m.group(2), m.group(1))
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return "%s-%s-%sT00:00:00" % (m.group(1), m.group(2), m.group(3))
    return None


def _link(url_title, edition_date, secao):
    if url_title:
        return "https://www.in.gov.br/web/dou/-/" + url_title
    num = re.sub(r"E$", "", secao, flags=re.I).replace("DO", "")
    return "https://www.in.gov.br/web/dou/-/dou/%s/secao-%s/" % (edition_date, num)


def parse_article_xml(xml_bytes, file_name, edition_date, secao):
    root = ET.fromstring(xml_bytes)
    article = _find_article(root)
    attrs = {k.lower(): v for k, v in article.attrib.items()}

    identifica = _text_by_names(article, ["Identifica"])
    titulo_tag = _text_by_names(article, ["Titulo"])
    ementa = _text_by_names(article, ["Ementa"])
    subtitulo = _text_by_names(article, ["SubTitulo", "Subtitulo"])

    texto_el = _el_by_names(article, ["Texto"])
    texto_raw = "".join(texto_el.itertext()) if texto_el is not None else ""
    texto = _strip_html(texto_raw)[:12000]

    title = identifica or titulo_tag or ementa or re.sub(r"\.xml$", "", file_name, flags=re.I)
    orgao = attrs.get("artcategory") or _text_by_names(article, ["NomeOrgao", "Orgao"])
    pub_name = attrs.get("pubname", "")
    art_type = attrs.get("arttype", "")
    url_title = attrs.get("name") or attrs.get("urltitle", "")
    pub_date_raw = attrs.get("pubdate") or _text_by_names(article, ["pubDate", "Data"])

    published_iso = _parse_date(pub_date_raw, edition_date)

    return {
        "source": "INLABS",
        "externalId": file_name + "@" + edition_date,
        "fileName": file_name,
        "title": _norm(title),
        "subtitle": _norm(subtitulo),
        "ementa": _norm(ementa or pub_name or art_type),
        "orgao": _norm(orgao),
        "textoResumo": texto,
        "link": _link(url_title, edition_date, secao),
        "publishedAt": published_iso,
        "publishedIso": published_iso or edition_date,
        "secao": secao,
        "editionDate": edition_date,
        "pubName": pub_name,
        "artType": art_type,
    }
