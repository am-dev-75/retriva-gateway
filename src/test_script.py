import asyncio
from retriva_gateway.core.intent import Intent, IntentDetector

# Mock schema
async def mock_get_schema():
    return {
        "properties": {
            "project": {"type": "string"},
            "department": {"type": "string"}
        }
    }

IntentDetector._get_schema = mock_get_schema

async def run_tests():
    # 'List all documents for project apollo' is classified as catalog_document_list.
    i, m = await IntentDetector.analyze("List all documents for project apollo")
    assert i == Intent.CATALOG_DOCUMENT_LIST, f"Failed: {i}"
    assert m == {"project": "apollo"}, f"Failed meta: {m}"

    # 'List all the documents you have dealing with apollo project' is classified as catalog_document_list.
    i, m = await IntentDetector.analyze("List all the documents you have dealing with apollo project")
    assert i == Intent.CATALOG_DOCUMENT_LIST, f"Failed: {i}"
    assert m == {"project": "apollo"}, f"Failed meta: {m}"

    # 'How many documents are tagged project apollo?' is classified as catalog_document_count.
    i, m = await IntentDetector.analyze("How many documents are tagged project apollo?")
    assert i == Intent.CATALOG_DOCUMENT_COUNT, f"Failed: {i}"
    assert m == {"project": "apollo"}, f"Failed meta: {m}"

    # 'What are the costs for project apollo?' is classified as metadata_filtered_rag.
    i, m = await IntentDetector.analyze("What are the costs for project apollo?")
    assert i == Intent.METADATA_FILTERED_RAG, f"Failed: {i}"
    assert m == {"project": "apollo"}, f"Failed meta: {m}"

    print("All tests passed!")

asyncio.run(run_tests())
