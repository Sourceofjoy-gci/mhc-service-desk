import {
  afterEach,
  beforeEach,
  describe,
  expect,
  expectTypeOf,
  it,
  vi,
} from "vitest";
import {
  ApiError,
  apiProblem,
  attachmentsApi,
  configureApiAuth,
  domainCapabilities,
  ticketsApi,
  type ActivityItem,
  type AssignmentParty,
  type AssignmentRequest,
  type AssignmentResponse,
  type TicketAssignee,
  type TicketCapabilities,
  type TicketDetail,
  type TicketSummary,
  type TicketTransitionRequest,
  type TicketWorkStateUpdate,
} from "./api";

function jsonResponse(status: number, body: unknown = {}) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function request(call: [input: RequestInfo | URL, init?: RequestInit]): {
  url: RequestInfo | URL;
  init: RequestInit;
} {
  return { url: call[0], init: call[1] ?? {} };
}

function assignmentResponse(): AssignmentResponse {
  return {
    ticket: {
      id: "ticket-1",
      number: "OP-202607-000001",
      domain: "operational",
      title: "Estate review",
      channel: "web",
      priority: "P2",
      confidentiality: "normal",
      status_code: "assigned",
      status_name: "Assigned",
      status_public: "In progress",
      requester_name: "Naledi Dube",
      office_code: "MBABANE",
      service_code: "ESTATES",
      assignee: "00000000-0000-0000-0000-000000000012",
      waiting_reason: "",
      created_at: "2026-07-30T08:00:00Z",
      updated_at: "2026-07-30T10:01:00Z",
      age_hours: 2,
      sla_health: "on_track",
      available_transition_codes: ["in_progress"],
      description: "Review the estate file.",
      requester: {
        id: "requester-1",
        full_name: "Naledi Dube",
        email: "naledi@example.test",
        phone_e164: null,
      },
      service: "Estates",
      request_type: "Estate review",
      office: "Mbabane",
      matter_reference: "EST-42",
      tags: [],
      custom_fields: {},
      resolution_code: "",
      resolution_summary: "",
      acknowledged_at: "2026-07-30T08:15:00Z",
      first_responded_at: null,
      resolved_at: null,
      closed_at: null,
      reopened_at: null,
      assignee_detail: {
        id: "00000000-0000-0000-0000-000000000012",
        display_name: "Finance Reviewer",
      },
      team: "Finance",
      blocked_reason: "",
      next_action: "Review account",
      next_action_at: "2026-07-31T08:00:00Z",
      available_transitions: [
        {
          to_status: "in_progress",
          label: "Start work",
          requires_resolution: false,
          requires_reason: false,
        },
      ],
      capabilities: {
        can_update_work_state: true,
        can_self_assign: false,
        self_assignee_id: null,
        self_assignee_detail: null,
        can_assign: true,
        can_reassign: true,
        can_change_confidentiality: true,
        can_add_message: true,
        can_add_note: true,
        can_upload_attachment: true,
      },
      sla_clocks: {
        first_response: {
          state: "met",
          due_at: "2026-07-30T10:00:00Z",
          remaining_seconds: 0,
          overdue_seconds: 0,
        },
        resolution: {
          state: "running",
          due_at: "2026-07-31T08:00:00Z",
          remaining_seconds: 79_140,
          overdue_seconds: 0,
        },
      },
      relationships: [],
      attachments: [],
      messages: [],
      notes: [],
    },
    receipt: {
      ticket_number: "OP-202607-000001",
      action: "reassigned",
      previous_assignee: {
        id: "00000000-0000-0000-0000-000000000011",
        display_name: "Estate Examiner",
        designations: ["Estate Examiner"],
        team_labels: ["Estate Administration"],
      },
      new_assignee: {
        id: "00000000-0000-0000-0000-000000000012",
        display_name: "Finance Reviewer",
        designations: ["Accountant"],
        team_labels: ["Finance"],
      },
      occurred_at: "2026-07-30T10:01:00Z",
      performed_by: {
        kind: "user",
        subject: "supervisor-1",
        display_name: "Operations Supervisor",
      },
    },
  };
}

describe("ticket lifecycle API contracts", () => {
  let disposeAuth: () => void;

  beforeEach(() => {
    disposeAuth = configureApiAuth({
      getAccessToken: vi.fn().mockResolvedValue("staff-token"),
      refresh: vi.fn().mockResolvedValue(false),
      login: vi.fn().mockResolvedValue(undefined),
    });
  });

  afterEach(() => {
    disposeAuth();
  });

  it("PATCHes work-state values with the concurrency timestamp intact", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200));
    const values = {
      updated_at: "2026-07-27T08:00:00Z",
      next_action: "Call requester",
      next_action_at: "2026-07-28T08:00:00Z",
    } satisfies TicketWorkStateUpdate;

    await ticketsApi.updateWorkState("OP-202607-000001", values);

    const { url, init } = request(fetchMock.mock.calls[0]);
    expect(url).toBe(
      "/api/v1/tickets/OP-202607-000001/work-state/",
    );
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual(values);
  });

  it("POSTs the complete transition payload without dropping resolution data", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200));
    const values = {
      to_status: "resolved",
      updated_at: "2026-07-27T08:00:00Z",
      reason: "Completed",
      resolution_code: "INFO_PROVIDED",
      resolution_summary:
        "The requester received the required information.",
    } satisfies TicketTransitionRequest;

    await ticketsApi.transition("OP-202607-000001", values);

    const { url, init } = request(fetchMock.mock.calls[0]);
    expect(url).toBe(
      "/api/v1/tickets/OP-202607-000001/transition/",
    );
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual(values);
  });

  it("loads activity and eligible assignees from ticket subresources", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, { results: [] }))
      .mockResolvedValueOnce(jsonResponse(200, { results: [] }));

    await ticketsApi.activity("OP-202607-000001");
    await ticketsApi.assignees("OP-202607-000001");

    expect(request(fetchMock.mock.calls[0])).toMatchObject({
      url: "/api/v1/tickets/OP-202607-000001/activity/",
      init: { method: "GET" },
    });
    expect(request(fetchMock.mock.calls[1])).toMatchObject({
      url: "/api/v1/tickets/OP-202607-000001/assignees/",
      init: { method: "GET" },
    });
  });

  it("encodes candidate search against the guarded ticket subresource", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, { results: [] }));

    await ticketsApi.assignees(
      "OP-202607-000001",
      "account & finance",
    );

    expect(request(fetchMock.mock.calls[0])).toMatchObject({
      url:
        "/api/v1/tickets/OP-202607-000001/assignees/?search=account+%26+finance",
      init: { method: "GET" },
    });
  });

  it("POSTs the exact assignment command and returns its authoritative response", async () => {
    const response = assignmentResponse();
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, response));
    const values = {
      assignee_id: "00000000-0000-0000-0000-000000000012",
      expected_updated_at: "2026-07-30T10:00:00Z",
      reason: "Transfer to finance review",
    } satisfies AssignmentRequest;

    await expect(
      ticketsApi.assign("OP-202607-000001", values),
    ).resolves.toEqual(response);

    const { url, init } = request(fetchMock.mock.calls[0]);
    expect(url).toBe(
      "/api/v1/tickets/OP-202607-000001/assignment/",
    );
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual(values);
  });

  it("lists and uploads attachments through the ticket collection", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, { results: [] }))
      .mockResolvedValueOnce(jsonResponse(201, { results: [] }));
    const first = new File(["first"], "first.txt", { type: "text/plain" });
    const second = new File(["second"], "second.txt", { type: "text/plain" });

    await attachmentsApi.list("OP-202607-000001");
    await attachmentsApi.upload("OP-202607-000001", [first, second]);

    expect(request(fetchMock.mock.calls[0])).toMatchObject({
      url: "/api/v1/tickets/OP-202607-000001/attachments/",
      init: { method: "GET" },
    });
    const upload = request(fetchMock.mock.calls[1]);
    expect(upload.url).toBe(
      "/api/v1/tickets/OP-202607-000001/attachments/",
    );
    expect(upload.init.method).toBe("POST");
    expect(upload.init.body).toBeInstanceOf(FormData);
    expect(Array.from((upload.init.body as FormData).getAll("files"))).toEqual([
      first,
      second,
    ]);
    expect(new Headers(upload.init.headers).has("Content-Type")).toBe(false);
  });

  it("requests a signed attachment download from the attachment resource", async () => {
    const response = {
      url: "https://files.example/signed",
      filename: "proof.pdf",
      expires_in: 60,
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, response));
    await expect(attachmentsApi.download("attachment-1")).resolves.toEqual(
      response,
    );
    expect(request(fetchMock.mock.calls[0])).toMatchObject({
      url: "/api/v1/attachments/attachment-1/download/",
      init: { method: "GET" },
    });
  });

  it("requires accepted lifecycle fields at compile time", () => {
    expectTypeOf<TicketSummary["available_transition_codes"]>().toEqualTypeOf<
      string[]
    >();
    expectTypeOf(ticketsApi.transition).toEqualTypeOf<
      (
        number: string,
        values: TicketTransitionRequest,
      ) => Promise<TicketDetail>
    >();
    expectTypeOf<TicketCapabilities["can_assign"]>().toEqualTypeOf<boolean>();
    expectTypeOf<
      TicketCapabilities["self_assignee_detail"]
    >().toEqualTypeOf<TicketAssignee | null>();
    expectTypeOf<TicketAssignee["designations"]>().toEqualTypeOf<string[]>();
    expectTypeOf<TicketAssignee["team_labels"]>().toEqualTypeOf<string[]>();
    expectTypeOf<ActivityItem["type"]>().toEqualTypeOf<
      | "message"
      | "internal_note"
      | "status_transition"
      | "work_state"
      | "attachment"
      | "relationship"
      | "custody_event"
    >();
    expectTypeOf<ActivityItem["category"]>().toEqualTypeOf<
      | "public_reply"
      | "internal_note"
      | "workflow"
      | "custody"
      | "attachment"
      | "relationship"
    >();
    expectTypeOf<AssignmentParty>().toEqualTypeOf<{
      id: string;
      display_name: string;
      designations: string[];
      team_labels: string[];
    }>();
    expectTypeOf(ticketsApi.assign).toEqualTypeOf<
      (
        number: string,
        body: AssignmentRequest,
      ) => Promise<AssignmentResponse>
    >();
    expectTypeOf(domainCapabilities(["master"]).queueDomains).toEqualTypeOf<
      ("operational" | "it")[]
    >();
  });
});

describe("canonical API problems", () => {
  it("exposes only complete canonical error bodies", () => {
    const problem = {
      code: "stale_ticket",
      detail: "The ticket was updated by another user.",
      fields: { updated_at: ["2026-07-27T09:00:00Z"] },
      correlation_id: "corr-123",
    };

    expect(apiProblem(new ApiError(409, problem))).toEqual(problem);
    expect(
      apiProblem(
        new ApiError(400, {
          code: "invalid_work_state",
          detail: "Work state is invalid.",
          fields: { next_action: "Must be text." },
          correlation_id: "corr-124",
        }),
      ),
    ).toBeNull();
    expect(apiProblem(new Error("network"))).toBeNull();
  });
});
