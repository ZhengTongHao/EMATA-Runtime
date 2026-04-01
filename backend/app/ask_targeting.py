from typing import Any, Dict, List


class AskTargetResolver:
    def resolve_search_results(self, *, query: str, user: Any, tools: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        normalized_query = (query or "").strip()
        if not normalized_query:
            return {"contacts": [], "chats": []}

        contacts: List[Dict[str, Any]] = []
        chats: List[Dict[str, Any]] = []

        try:
            contact_result = tools["lark_cli"].execute(
                {"capability": "contact.resolve", "query": normalized_query},
                user=user,
            )
            for item in contact_result.get("matches", [])[:3]:
                open_id = str(item.get("open_id") or "")
                if not open_id:
                    continue
                contacts.append(
                    {
                        "kind": "user",
                        "label": str(item.get("name") or normalized_query),
                        "value": open_id,
                        "query": normalized_query,
                    }
                )
        except Exception:
            pass

        try:
            chat_result = tools["lark_cli"].execute(
                {"capability": "chat.resolve", "query": normalized_query},
                user=user,
            )
            for item in chat_result.get("matches", [])[:3]:
                chat_id = str(item.get("chat_id") or item.get("id") or "")
                if not chat_id:
                    continue
                chats.append(
                    {
                        "kind": "chat",
                        "label": str(item.get("name") or item.get("chat_name") or normalized_query),
                        "value": chat_id,
                        "query": normalized_query,
                    }
                )
        except Exception:
            pass

        return {
            "contacts": self._dedupe(contacts),
            "chats": self._dedupe(chats),
        }

    def resolve_candidates(self, *, query: str, user: Any, tools: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = self.resolve_search_results(query=query, user=user, tools=tools)
        return [*results["contacts"], *results["chats"]][:3]

    def resolve_exact_candidate(
        self,
        *,
        query: str,
        user: Any,
        tools: Dict[str, Any],
        preferred_kind: str = "",
    ) -> Dict[str, Any]:
        normalized_query = (query or "").strip().lower()
        if not normalized_query:
            return {}

        results = self.resolve_search_results(query=query, user=user, tools=tools)
        ordered_groups = []
        if preferred_kind == "chat":
            ordered_groups = [results["chats"], results["contacts"]]
        elif preferred_kind == "user":
            ordered_groups = [results["contacts"], results["chats"]]
        else:
            ordered_groups = [results["contacts"], results["chats"]]

        exact_matches: List[Dict[str, Any]] = []
        for group in ordered_groups:
            group_matches = [
                item
                for item in group
                if str(item.get("label") or "").strip().lower() == normalized_query
            ]
            if group_matches:
                exact_matches.extend(group_matches)
                break

        if len(exact_matches) == 1:
            return exact_matches[0]
        return {}

    @staticmethod
    def _dedupe(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for item in matches:
            key = (item["kind"], item["value"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped
