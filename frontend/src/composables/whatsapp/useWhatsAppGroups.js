import { ref, watch } from "vue";
export function useWhatsAppGroups({
  groupInfo,
  groupDescription,
  inviteLink,
  joinRequests,
  groupCursor,
  notice,
  groups,
  group,
  text,
  subject,
  body,
  execute,
  run,
  enqueue,
}) {
  const joinCursor = ref("");
  const newGroupSubject = ref(""), newGroupDescription = ref("");
  const joinApprovalMode = ref("approval_required");
  watch(group, () => { joinCursor.value = ""; });
  async function requestPage(after = "") {
    const result = await execute("groups.requests.list", { id: group.value, ...(after ? {after} : {}) });
    joinRequests.value = result.data || [];
    joinCursor.value = result.paging?.cursors?.after || "";
  }
  async function nextJoinRequests() { await run(() => requestPage(joinCursor.value)); }
  function groupRows(r) {
    return Array.isArray(r.data) ? r.data : r.data?.groups || [];
  }

  async function inspectGroup() {
    await run(async () => {
      groupInfo.value = await execute("groups.info", { id: group.value });
      subject.value = groupInfo.value.subject || "";
      groupDescription.value = groupInfo.value.description || "";
      await requestPage();
    });
  }

  async function manageGroup(operation, args = {}) {
    await run(async () => {
      const r = await execute(operation, { id: group.value, ...args });
      if (operation.startsWith("groups.invite."))
        inviteLink.value = r.invite_link || "";
      if (
        operation === "groups.update" ||
        operation.startsWith("groups.participants.")
      )
        groupInfo.value = await execute("groups.info", { id: group.value });
      notice.value = "Request accepted";
      if (operation.startsWith("groups.requests.")) await requestPage();
      if (operation === "groups.delete") {
        groups.value = groups.value.filter(row => row.id !== group.value);
        group.value = "";
        groupInfo.value = null;
      }
    });
  }

  async function nextGroups() {
    await run(async () => {
      const r = await execute("groups.list", { after: groupCursor.value });
      groups.value = groupRows(r);
      groupCursor.value = r.paging?.cursors?.after || "";
      group.value = "";
      groupInfo.value = null;
    });
  }

  async function createGroup() {
    await run(async () => {
      await execute("groups.create", {
        subject: newGroupSubject.value,
        description: newGroupDescription.value,
        join_approval_mode: joinApprovalMode.value,
      });
      newGroupSubject.value = "";
      newGroupDescription.value = "";
      notice.value = "Group creation requested";
      groups.value = groupRows(await execute("groups.list"));
    });
  }

  async function sendGroup() {
    await run(async () => {
      await enqueue("groups.send", { id: group.value, body: text.value }, [""]);
      text.value = "";
    });
  }
  return {
    joinCursor, joinApprovalMode, nextJoinRequests, newGroupSubject, newGroupDescription,
    groupRows,
    inspectGroup,
    manageGroup,
    nextGroups,
    createGroup,
    sendGroup,
  };
}
