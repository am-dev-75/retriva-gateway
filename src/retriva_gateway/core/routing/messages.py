# Copyright (C) 2026 Andrea Marson (am.dev.75@gmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Closed, deterministic user-facing messages (EN/IT).

Every string here is static and closed: no model-generated text, no
user-content echo, no free-form interpolation beyond closed labels.
Languages outside ``en``/``it`` fall back to English (documented in the
runbook and the Spec 040 delivery record).
"""

from __future__ import annotations

import re
from typing import Dict, Optional

SUPPORTED_LANGUAGES = ("en", "it")


def normalize_language(language: Optional[str]) -> str:
    value = (language or "").strip().lower()
    return value if value in SUPPORTED_LANGUAGES else "en"


_ITALIAN_WORDS = re.compile(
    r"\b(?:come|cosa|quante|quanti|quale|perch|vorrei|posso|devo|deve|"
    r"puoi|abbiamo|sono|questo|questa|questi|queste|il|lo|la|i|gli|le|"
    r"un|una|uno|di|del|della|dei|degli|delle|che|per|con|non|"
    r"aziende|azienda|campagna|campagne|esporta|esportare|importa|"
    r"attiva|attivare|approva|approvare|conferma|confermare|verifica|"
    r"mostra|elenca|imposta|configura|crea|creare|cancella|aggiorna|"
    r"elimina|ripristina|sostituisci|invia|genera|analizza|qualifica|"
    r"seleziona|rifiuta|escludi|aggiungi|rimuovi|carica|scarica|"
    r"presentazione|righe|dati)\b", re.IGNORECASE)
_ENGLISH_WORDS = re.compile(
    r"\b(?:the|and|of|to|how|many|what|which|export|import|create|"
    r"approve|confirm|activate|campaigns?|companies|company|"
    r"presentation|file|excel)\b", re.IGNORECASE)
_ACCENTED = re.compile(r"[\u00e0\u00e8\u00e9\u00ec\u00f2\u00f9]")


def detect_language(message: str) -> str:
    """Deterministic, conservative IT/EN detection; default English.

    Scores Italian action words/articles and English function words; an
    accented character is a strong Italian signal. Ties default to English
    only when there is no Italian signal at all.
    """
    text = message or ""
    italian = len(_ITALIAN_WORDS.findall(text))
    english = len(_ENGLISH_WORDS.findall(text))
    if _ACCENTED.search(text):
        italian += 1
    if italian > english:
        return "it"
    if english > italian:
        return "en"
    return "en"


FAMILY_LABELS: Dict[str, Dict[str, str]] = {
    "en": {
        "ACP": "ACP / reference cohorts",
        "QUALIFICATION": "qualification",
        "COMPANY_IMPORT": "company import",
        "CAMPAIGN": "campaigns",
        "DOCUMENTATION": "documentation",
        "GENERAL": "general",
    },
    "it": {
        "ACP": "ACP / coorti di riferimento",
        "QUALIFICATION": "qualificazione",
        "COMPANY_IMPORT": "import aziende",
        "CAMPAIGN": "campagne",
        "DOCUMENTATION": "documentazione",
        "GENERAL": "generale",
    },
}

OPERATION_LABELS: Dict[str, Dict[str, str]] = {
    "en": {
        "ACP_COHORT_APPROVAL": "approve the cohort proposal",
        "ACP_APPROVAL": "approve the ACP version",
        "ACP_ACTIVATION": "activate the ACP version",
        "ACP_SUPERSESSION": "supersede the active ACP",
        "ACP_ROLLBACK": "roll back the ACP",
        "ACP_EVIDENCE_ENRICHMENT": "start the evidence enrichment",
        "ACP_EVIDENCE_ACCEPTANCE": "accept the enrichment evidence",
        "QUALIFICATION_APPROVAL": "approve the qualification results",
        "COMPANY_IMPORT_APPROVAL": "approve the import batch",
        "COMPANY_IMPORT_COMMIT": "commit the import batch",
        "CAMPAIGN_AUDIENCE_APPROVAL": "approve the campaign audience",
        "CAMPAIGN_AUDIENCE_COMMIT": "commit the campaign audience",
        "CAMPAIGN_HISTORY_IMPORT": "import the campaign history",
        "CAMPAIGN_MARK_ADDRESSED": "mark the campaign audience addressed",
        "CAMPAIGN_OUTCOME_UPDATE": "update the campaign outcome",
    },
    "it": {
        "ACP_COHORT_APPROVAL": "approvare la proposta di coorte",
        "ACP_APPROVAL": "approvare la versione ACP",
        "ACP_ACTIVATION": "attivare la versione ACP",
        "ACP_SUPERSESSION": "sostituire l'ACP attivo",
        "ACP_ROLLBACK": "ripristinare l'ACP",
        "ACP_EVIDENCE_ENRICHMENT": "avviare l'arricchimento delle evidenze",
        "ACP_EVIDENCE_ACCEPTANCE": "accettare le evidenze di arricchimento",
        "QUALIFICATION_APPROVAL": "approvare i risultati di qualificazione",
        "COMPANY_IMPORT_APPROVAL": "approvare il batch di import",
        "COMPANY_IMPORT_COMMIT": "confermare il batch di import",
        "CAMPAIGN_AUDIENCE_APPROVAL": "approvare il pubblico della campagna",
        "CAMPAIGN_AUDIENCE_COMMIT": "confermare il pubblico della campagna",
        "CAMPAIGN_HISTORY_IMPORT": "importare lo storico della campagna",
        "CAMPAIGN_MARK_ADDRESSED": "segnare il pubblico della campagna come indirizzato",
        "CAMPAIGN_OUTCOME_UPDATE": "aggiornare l'esito della campagna",
    },
}

CLARIFY_TEMPLATES: Dict[str, Dict] = {
    "en": {
        "multi_intent": (
            "This message mentions more than one action ({families}). "
            "Please send each action as a separate message; consequential "
            "actions require explicit confirmation."),
        "unsupported": (
            "That operation ({operation}) is not available from chat: it "
            "is not exposed as a chat workflow. Use the CRM console, or "
            "ask me how it works and I will answer from the documentation."),
        "unavailable_vocabulary": (
            "I recognized a possible {family} request, but this operation "
            "is not available as an explicit chat command yet. Please "
            "restate it as a separate, explicit request (for example with "
            "the exact resource identifier), or ask me how the workflow "
            "works."),
        "consequential_resource": (
            "To {operation} I need the exact resource identifier (for "
            "example an ACP version id like acpver_…, a qualification job "
            "id like job_…, or an import batch id) and your explicit "
            "request. Which resource do you want to {operation}?"),
        "followup": (
            "I don't have an active workflow context for this reply. "
            "Please restate the action you want, including the exact "
            "resource (for example a version or job identifier)."),
        "adjacent": (
            "I'm not sure whether you want an explanation or a workflow "
            "action. Please restate your request as either a question "
            "(for example: 'how does ACP activation work?') or an explicit "
            "command (for example: 'activate ACP version acpver_…')."),
        "family_ambiguous": {
            "ACP": (
                "Do you want me to explain how ACP generation works, or "
                "create a new PostgreSQL-backed cohort proposal for review?"),
            "QUALIFICATION": (
                "Do you want an explanation of how qualification works, or "
                "should I start a qualification analysis of your candidates?"),
            "COMPANY_IMPORT": (
                "Do you want to know how company imports work, or should I "
                "analyze an import batch for you?"),
            "CAMPAIGN": (
                "Do you want an overview of campaign tracking, or should I "
                "analyze a campaign audience for you?"),
        },
        "router_clarify": (
            "I can answer that from the knowledge base or from a read-only "
            "Company Intelligence workflow, but I could not choose a safe "
            "data plane. Please rephrase, or name the campaign or workflow "
            "family."),
        "router_failure": (
            "I could not safely determine which data source should answer "
            "that. No tool was executed and no data was changed. Please "
            "rephrase the request."),
        "router_action_campaign": (
            "The requested action is not an available read-only capability. "
            "Available campaign reads are: campaign list, per-campaign "
            "company and addressed stats, campaign lineage, campaign "
            "history, and campaign-companies Excel export. I can run one "
            "of those instead."),
        "router_action_generic": (
            "The requested action is not an available read-only capability "
            "for that family. I can only run read-only operations that are "
            "exposed in the current catalog."),
        "streaming_refusal": (
            "Workflow operations require a non-streaming request. Resend "
            "the same request without streaming to run the operation."),
        "qualification_error": (
            "Candidate qualification cannot be executed from this chat: "
            "{error}. I will not simulate scores or Web Research results."),
        "agent_error": (
            "The requested workflow cannot be executed from this chat: "
            "{error}. I will not simulate or guess workflow results."),
        "loop_no_tools": (
            "I could not produce a response for that request. No tool was "
            "executed and no data was changed. Please restate the request; "
            "if you were continuing a staged workflow, ask me to show its "
            "current state first."),
        "loop_length": (
            "The model reached its response-length limit before it "
            "produced a final answer, so no tool was executed and no data "
            "was changed. Please retry the request or split it into a "
            "smaller step."),
        "loop_tool_ok": (
            "The `{name}` step completed: {summary} No additional "
            "narrative was generated."),
        "loop_tool_error": (
            "I attempted `{name}`, but it failed{detail}. No further "
            "action was taken."),
        "loop_tool_success_no_summary": (
            "The `{name}` step completed successfully, but no final summary "
            "was generated. Ask me for the current state to continue."),
        "loop_tool_failed": (
            "`{name}` did not complete, and no final summary was generated. "
            "No further action was taken."),
        "tool_not_available": (
            "This tool is not available on a read-only route."),
        "tool_timeout": "Tool {name} timed out after {seconds}s.",
        "tool_unavailable": "Tool {name!r} is not available.",
        "tool_repeated": (
            "Tool {name!r} was already called with identical arguments; "
            "repeated calls are ignored."),
        "iteration_limit": (
            "The workflow reached the tool-call limit ({max_iterations} "
            "iterations) without a final answer. No further action was "
            "taken; check the current state before retrying."),
    },
    "it": {
        "multi_intent": (
            "Questo messaggio contiene più di un'azione ({families}). "
            "Invia ogni azione in un messaggio separato; le azioni "
            "consequenziali richiedono una conferma esplicita."),
        "unsupported": (
            "L'operazione richiesta ({operation}) non è disponibile dalla "
            "chat: non è esposta come workflow. Usa la console CRM, oppure "
            "chiedimi come funziona e risponderò dalla documentazione."),
        "unavailable_vocabulary": (
            "Ho riconosciuto una possibile richiesta {family}, ma questa "
            "operazione non è ancora disponibile come comando esplicito "
            "della chat. Riformulala come richiesta separata ed esplicita "
            "(ad esempio con l'identificatore esatto della risorsa), oppure "
            "chiedimi come funziona il workflow."),
        "consequential_resource": (
            "Per {operation} mi serve l'identificatore esatto della risorsa "
            "(ad esempio un id versione ACP come acpver_…, un id job di "
            "qualificazione come job_…, o un id batch di import) e la tua "
            "richiesta esplicita. Quale risorsa vuoi usare per {operation}?"),
        "followup": (
            "Non ho un contesto workflow attivo per questa risposta. "
            "Riformula l'azione desiderata, includendo la risorsa esatta "
            "(ad esempio un identificatore di versione o di job)."),
        "adjacent": (
            "Non sono sicuro se vuoi una spiegazione o un'azione workflow. "
            "Riformula la richiesta come domanda (ad esempio: 'come funziona "
            "l'attivazione ACP?') oppure come comando esplicito (ad esempio: "
            "'attiva la versione ACP acpver_…')."),
        "family_ambiguous": {
            "ACP": (
                "Vuoi una spiegazione di come funziona la generazione ACP, "
                "oppure vuoi creare una nuova proposta di coorte PostgreSQL "
                "per la revisione?"),
            "QUALIFICATION": (
                "Vuoi una spiegazione di come funziona la qualificazione, "
                "oppure vuoi avviare un'analisi di qualificazione dei tuoi "
                "candidati?"),
            "COMPANY_IMPORT": (
                "Vuoi sapere come funzionano gli import di aziende, oppure "
                "vuoi analizzare un batch di import?"),
            "CAMPAIGN": (
                "Vuoi una panoramica del monitoraggio campagne, oppure vuoi "
                "analizzare il pubblico di una campagna?"),
        },
        "router_clarify": (
            "Posso rispondere dalla base di conoscenza o da un workflow di "
            "Company Intelligence in sola lettura, ma non riesco a scegliere "
            "un piano dati sicuro. Riformula la richiesta, oppure indica la "
            "campagna o la famiglia di workflow."),
        "router_failure": (
            "Non riesco a determinare in modo sicuro quale fonte dati debba "
            "rispondere. Nessuno strumento è stato eseguito e nessun dato è "
            "stato modificato. Riformula la richiesta."),
        "router_action_campaign": (
            "L'azione richiesta non è una capacità di sola lettura "
            "disponibile. Le letture disponibili per le campagne sono: "
            "elenco campagne, statistiche aziende e indirizzate per "
            "campagna, lineage della campagna, storico della campagna e "
            "esportazione Excel delle aziende della campagna. Posso "
            "eseguirne una."),
        "router_action_generic": (
            "L'azione richiesta non è una capacità di sola lettura "
            "disponibile per quella famiglia. Posso eseguire solo le "
            "operazioni di sola lettura esposte nel catalogo corrente."),
        "streaming_refusal": (
            "Le operazioni workflow richiedono una richiesta non in "
            "streaming. Invia la stessa richiesta senza streaming per "
            "eseguire l'operazione."),
        "qualification_error": (
            "La qualificazione dei candidati non può essere eseguita da "
            "questa chat: {error}. Non simulerò punteggi o risultati Web "
            "Research."),
        "agent_error": (
            "Il workflow richiesto non può essere eseguito da questa chat: "
            "{error}. Non simulerò né indovinerò i risultati del workflow."),
        "loop_no_tools": (
            "Non sono riuscito a produrre una risposta per quella richiesta. "
            "Nessuno strumento è stato eseguito e nessun dato è stato "
            "modificato. Riformula la richiesta; se stavi proseguendo un "
            "workflow già avviato, chiedimi prima il suo stato attuale."),
        "loop_length": (
            "Il modello ha raggiunto il limite di lunghezza della risposta "
            "prima di produrre una risposta finale, quindi nessuno strumento "
            "è stato eseguito e nessun dato è stato modificato. Riprova o "
            "suddividi la richiesta in un passaggio più piccolo."),
        "loop_tool_ok": (
            "Il passaggio `{name}` è completato: {summary} Non è stata "
            "generata un'ulteriore narrazione."),
        "loop_tool_error": (
            "Ho tentato `{name}`, ma è fallito{detail}. Nessun'altra azione "
            "è stata eseguita."),
        "loop_tool_success_no_summary": (
            "Il passaggio `{name}` è completato correttamente, ma non è stata "
            "generata una sintesi finale. Chiedimi lo stato attuale per "
            "proseguire."),
        "loop_tool_failed": (
            "`{name}` non è stato completato e non è stata generata una "
            "sintesi finale. Nessun'altra azione è stata eseguita."),
        "tool_not_available": (
            "Questo strumento non è disponibile su un percorso di sola "
            "lettura."),
        "tool_timeout": "Lo strumento {name} ha superato il timeout di {seconds}s.",
        "tool_unavailable": "Lo strumento {name!r} non è disponibile.",
        "tool_repeated": (
            "Lo strumento {name!r} è già stato chiamato con gli stessi "
            "argomenti; le chiamate ripetute vengono ignorate."),
        "iteration_limit": (
            "Il workflow ha raggiunto il limite di chiamate agli strumenti "
            "({max_iterations} iterazioni) senza una risposta finale. "
            "Nessun'altra azione è stata eseguita; controlla lo stato "
            "attuale prima di riprovare."),
    },
}


def template(language: Optional[str], key: str, **kwargs) -> str:
    lang = normalize_language(language)
    text = CLARIFY_TEMPLATES[lang][key]
    return text.format(**kwargs) if kwargs else text


def family_label(language: Optional[str], family: str) -> str:
    lang = normalize_language(language)
    return FAMILY_LABELS[lang].get(family, family)


def operation_label(language: Optional[str], intent_name: str) -> str:
    lang = normalize_language(language)
    return OPERATION_LABELS[lang].get(intent_name, (
        "l'operazione richiesta" if lang == "it"
        else "perform that operation"))


def router_clarify(language: Optional[str], *, failure: bool = False,
                   action: bool = False,
                   family: Optional[str] = None) -> str:
    if failure:
        return template(language, "router_failure")
    if action:
        key = ("router_action_campaign" if family == "CAMPAIGN"
               else "router_action_generic")
        return template(language, key)
    return template(language, "router_clarify")
