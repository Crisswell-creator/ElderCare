"""Consent workflow, granular permissions, revocation and patient-level data isolation."""

from __future__ import annotations

from tests.conftest import add_med, create_elder, join, register


def test_redeeming_a_code_grants_nothing_until_the_elder_approves():
    elder = register("Margaret Ellis")
    pid = create_elder(elder)
    daughter = register("Ruth Ellis")
    code = elder.post(
        f"/api/patients/{pid}/invitations", {"intended_role": "family", "note": "Ruth"}
    ).json()["code"]
    req = daughter.post("/api/invitations/redeem", {"code": code.lower().replace("-", " ")})
    assert req.status_code == 201 and req.json()["status"] == "pending"
    # Pending: no access of any kind, and the profile's existence is not confirmed.
    assert daughter.get(f"/api/patients/{pid}").status_code == 404
    assert daughter.get(f"/api/patients/{pid}/medications").status_code == 404
    # The elder sees the request with suggested (not granted) permissions.
    pending = elder.get(f"/api/patients/{pid}/access-requests").json()
    assert pending[0]["requester_email"] == "ruth.ellis@example.com"
    # Approving with no permissions is refused: access is never unrestricted by default.
    empty = elder.post(
        f"/api/patients/{pid}/access-requests/{req.json()['id']}/decision",
        {"decision": "approve", "permissions": []},
    )
    assert empty.status_code == 400
    ok = elder.post(
        f"/api/patients/{pid}/access-requests/{req.json()['id']}/decision",
        {"decision": "approve", "permissions": ["view_appointments"]},
    )
    assert ok.status_code == 200
    assert daughter.get(f"/api/patients/{pid}/appointments").status_code == 200
    assert daughter.get(f"/api/patients/{pid}/medications").status_code == 403
    assert daughter.get(f"/api/patients/{pid}").status_code == 403
    # the elder was notified of the request; the requester of the decision
    assert any(
        n["kind"] == "access_request" for n in elder.get("/api/notifications").json()["items"]
    )
    assert any(
        n["kind"] == "access_decision" for n in daughter.get("/api/notifications").json()["items"]
    )


def test_invitation_codes_are_single_use_expiring_and_revocable(clock):
    elder = register("Margaret Ellis")
    pid = create_elder(elder)
    a, b, c = register("A Person"), register("B Person"), register("C Person")
    code = elder.post(f"/api/patients/{pid}/invitations", {"intended_role": "family"}).json()
    assert a.post("/api/invitations/redeem", {"code": code["code"]}).status_code == 201
    assert b.post("/api/invitations/redeem", {"code": code["code"]}).status_code == 400

    expiring = elder.post(f"/api/patients/{pid}/invitations", {"intended_role": "caregiver"})
    clock.advance(hours=73)
    assert b.post("/api/invitations/redeem", {"code": expiring.json()["code"]}).status_code == 400

    revoked = elder.post(f"/api/patients/{pid}/invitations", {"intended_role": "caregiver"})
    elder.delete(f"/api/patients/{pid}/invitations/{revoked.json()['id']}")
    assert c.post("/api/invitations/redeem", {"code": revoked.json()["code"]}).status_code == 400
    states = {i["id"]: i["state"] for i in elder.get(f"/api/patients/{pid}/invitations").json()}
    assert states[code["id"]] == "redeemed" and states[revoked.json()["id"]] == "revoked"
    assert all(i["code"] is None for i in elder.get(f"/api/patients/{pid}/invitations").json())


def test_code_guessing_is_throttled_per_user():
    guesser = register("Guess Er")
    for _ in range(5):
        assert guesser.post("/api/invitations/redeem", {"code": "AAAAA-BBBBB"}).status_code == 400
    assert guesser.post("/api/invitations/redeem", {"code": "AAAAA-BBBBB"}).status_code == 429


def test_only_deciders_manage_access(circle):
    pid = circle.pid
    assert (
        circle.family.post(
            f"/api/patients/{pid}/invitations", {"intended_role": "family"}
        ).status_code
        == 403
    )
    assert circle.carer.get(f"/api/patients/{pid}/access-requests").status_code == 403
    members = circle.elder.get(f"/api/patients/{pid}/members").json()
    carer_mid = next(m["id"] for m in members if m["role"] == "caregiver")
    elder_mid = next(m["id"] for m in members if m["role"] == "elder")
    assert (
        circle.family.patch(
            f"/api/patients/{pid}/members/{carer_mid}", {"permissions": ["view_profile"]}
        ).status_code
        == 403
    )
    assert circle.family.delete(f"/api/patients/{pid}/members/{carer_mid}").status_code == 403
    assert circle.elder.delete(f"/api/patients/{pid}/members/{elder_mid}").status_code == 403


def test_permission_change_takes_effect_and_is_audited(circle):
    pid = circle.pid
    assert circle.carer.get(f"/api/patients/{pid}/adherence").status_code == 403
    members = circle.elder.get(f"/api/patients/{pid}/members").json()
    mid = next(m["id"] for m in members if m["role"] == "caregiver")
    res = circle.elder.patch(
        f"/api/patients/{pid}/members/{mid}",
        {"permissions": ["manage_medications", "view_adherence"]},
    )
    # managing implies viewing
    assert set(res.json()["permissions"]) == {
        "manage_medications",
        "view_medications",
        "view_adherence",
    }
    assert circle.carer.get(f"/api/patients/{pid}/adherence").status_code == 200
    log = circle.elder.get(f"/api/patients/{pid}/activity").json()["items"]
    assert log[0]["action"] == "access.permissions_changed"


def test_revoked_caregiver_loses_all_access_immediately(circle):
    pid = circle.pid
    med = add_med(circle.elder, pid, ["08:00"])
    assert circle.carer.get(f"/api/patients/{pid}/medications").status_code == 200
    members = circle.elder.get(f"/api/patients/{pid}/members").json()
    mid = next(m["id"] for m in members if m["role"] == "caregiver")
    assert circle.elder.delete(f"/api/patients/{pid}/members/{mid}").status_code == 204
    for url in (
        f"/api/patients/{pid}",
        f"/api/patients/{pid}/medications",
        f"/api/patients/{pid}/medications/{med['id']}",
        f"/api/patients/{pid}/doses",
        f"/api/patients/{pid}/overview",
        f"/api/patients/{pid}/emergency",
    ):
        assert circle.carer.get(url).status_code == 404, url
    assert all(m["patient_id"] != pid for m in circle.carer.get("/api/auth/memberships").json())
    actions = [
        e["action"] for e in circle.elder.get(f"/api/patients/{pid}/activity").json()["items"]
    ]
    assert "access.revoked" in actions


def test_patients_are_isolated_even_with_guessed_ids(circle):
    other = register("Olive Stranger")
    other_pid = create_elder(other, "Olive Stranger")
    other_med = add_med(other, other_pid, ["09:00"], name="Olive's Med")
    # Members of one circle cannot read another circle by id ...
    for url in (
        f"/api/patients/{other_pid}",
        f"/api/patients/{other_pid}/medications",
        f"/api/patients/{other_pid}/documents",
        f"/api/patients/{other_pid}/activity",
    ):
        assert circle.elder.get(url).status_code == 404, url
    # ... nor reach another patient's record through their own patient's path.
    assert (
        circle.elder.get(f"/api/patients/{circle.pid}/medications/{other_med['id']}").status_code
        == 404
    )
    assert (
        circle.elder.put(
            f"/api/patients/{circle.pid}/medications/{other_med['id']}",
            {
                "name": "x",
                "dose_amount": 1,
                "start_date": "2024-01-01",
                "times": [{"local_time": "08:00"}],
            },
        ).status_code
        == 404
    )
    # The other elder's own view is unaffected.
    assert other.get(f"/api/patients/{other_pid}/medications").json()[0]["name"] == "Olive's Med"


def test_one_self_profile_per_person():
    elder = register("Solo Person")
    create_elder(elder)
    again = elder.post("/api/patients", {"mode": "self", "full_name": "Solo Person"})
    assert again.status_code == 409


def test_trusted_representative_onboarding_and_elder_claim():
    son = register("Tom Ellis")
    weak = son.post(
        "/api/patients", {"mode": "representative", "full_name": "Edith Ellis", "attestation": "ok"}
    )
    assert weak.status_code == 422  # an attestation is mandatory and recorded
    res = son.post(
        "/api/patients",
        {
            "mode": "representative",
            "full_name": "Edith Ellis",
            "relationship_label": "Son",
            "attestation": "I hold lasting power of attorney for health and welfare decisions.",
        },
    )
    assert res.status_code == 201
    pid = res.json()["patient"]["id"]
    assert res.json()["patient"]["managed_by_representative"] is True
    assert res.json()["can_decide_access"] is True

    edith = register("Edith Ellis")
    code = son.post(f"/api/patients/{pid}/invitations", {"intended_role": "elder"}).json()["code"]
    req = edith.post("/api/invitations/redeem", {"code": code}).json()
    assert req["requested_role"] == "elder"
    son.post(f"/api/patients/{pid}/access-requests/{req['id']}/decision", {"decision": "approve"})
    profile = edith.get(f"/api/patients/{pid}").json()
    assert (
        profile["my_role"] == "elder" and profile["patient"]["managed_by_representative"] is False
    )
    # Now the elder is in charge: the representative cannot remove another representative
    # designation decision, and the elder can remove the representative.
    members = edith.get(f"/api/patients/{pid}/members").json()
    son_mid = next(m["id"] for m in members if m["user_id"] == son.user["id"])
    assert edith.delete(f"/api/patients/{pid}/members/{son_mid}").status_code == 204
    assert son.get(f"/api/patients/{pid}/members").status_code == 404
    assert (
        son.post(f"/api/patients/{pid}/invitations", {"intended_role": "elder"}).status_code == 404
    )


def test_only_elder_designates_representatives(circle):
    pid = circle.pid
    members = circle.elder.get(f"/api/patients/{pid}/members").json()
    fam = next(m["id"] for m in members if m["role"] == "family")
    res = circle.elder.patch(f"/api/patients/{pid}/members/{fam}", {"is_representative": True})
    assert res.status_code == 200 and "manage_care_team" in res.json()["permissions"]
    # The representative can now decide access but not demote/remove the elder.
    assert circle.family.get(f"/api/patients/{pid}/access-requests").status_code == 200
    carer = next(m["id"] for m in members if m["role"] == "caregiver")
    assert (
        circle.family.patch(
            f"/api/patients/{pid}/members/{carer}", {"is_representative": True}
        ).status_code
        == 403
    )


def test_member_can_leave_and_rejoin_needs_new_consent(circle):
    pid = circle.pid
    members = circle.family.get(f"/api/patients/{pid}/members").json()
    me = next(m["id"] for m in members if m["is_me"])
    assert circle.family.delete(f"/api/patients/{pid}/members/{me}").status_code == 204
    assert circle.family.get(f"/api/patients/{pid}/members").status_code == 404
    join(circle.elder, pid, circle.family, "family", ["view_profile"])
    assert circle.family.get(f"/api/patients/{pid}/medications").status_code == 403


def test_requests_can_be_rejected_or_withdrawn():
    elder = register("Margaret Ellis")
    pid = create_elder(elder)
    x, y = register("X Ray"), register("Y Zed")
    c1 = elder.post(f"/api/patients/{pid}/invitations", {"intended_role": "family"}).json()
    c2 = elder.post(f"/api/patients/{pid}/invitations", {"intended_role": "family"}).json()
    r1 = x.post("/api/invitations/redeem", {"code": c1["code"]}).json()
    r2 = y.post("/api/invitations/redeem", {"code": c2["code"]}).json()
    rej = elder.post(
        f"/api/patients/{pid}/access-requests/{r1['id']}/decision", {"decision": "reject"}
    )
    assert rej.json()["status"] == "rejected"
    assert x.get(f"/api/patients/{pid}").status_code == 404
    assert y.post(f"/api/access-requests/{r2['id']}/withdraw").json()["status"] == "withdrawn"
    assert (
        elder.post(
            f"/api/patients/{pid}/access-requests/{r2['id']}/decision",
            {"decision": "approve", "permissions": ["view_profile"]},
        ).status_code
        == 409
    )
    assert {r["status"] for r in x.get("/api/access-requests/mine").json()} == {"rejected"}


def test_representative_cannot_claim_elder_role_with_own_second_account():
    """Security review M1: sock-puppet elder claim by a representative is refused."""
    rep = register("Rep One")
    pid = rep.post(
        "/api/patients",
        {
            "mode": "representative",
            "full_name": "Ada Lovell",
            "attestation": "I hold lasting power of attorney for this person.",
        },
    ).json()["patient"]["id"]
    # a second representative account controlled by the same person
    puppet = register("Puppet Account")
    join(rep, pid, puppet, "family", ["view_profile"])
    code = rep.post(f"/api/patients/{pid}/invitations", {"intended_role": "elder"}).json()["code"]
    # the puppet is already a member: redeeming is refused outright
    assert puppet.post("/api/invitations/redeem", {"code": code}).status_code == 409
    # an unverified claimant cannot take over either
    stranger = register("Fake Ada", verify=False)
    code2 = rep.post(f"/api/patients/{pid}/invitations", {"intended_role": "elder"}).json()["code"]
    req = stranger.post("/api/invitations/redeem", {"code": code2}).json()
    assert req["requester_email_verified"] is False
    res = rep.post(
        f"/api/patients/{pid}/access-requests/{req['id']}/decision", {"decision": "approve"}
    )
    assert res.status_code == 400
    # positive twin: a verified, unrelated claimant succeeds
    ada = register("Ada Lovell")
    code3 = rep.post(f"/api/patients/{pid}/invitations", {"intended_role": "elder"}).json()["code"]
    req3 = ada.post("/api/invitations/redeem", {"code": code3}).json()
    ok = rep.post(
        f"/api/patients/{pid}/access-requests/{req3['id']}/decision", {"decision": "approve"}
    )
    assert ok.status_code == 200


def test_representative_cannot_demote_another_representative():
    """Security review M2: update_member mirrors revoke_member's representative rule."""
    rep = register("Rep A")
    pid = rep.post(
        "/api/patients",
        {
            "mode": "representative",
            "full_name": "Bea Lovell",
            "attestation": "I hold lasting power of attorney for this person.",
        },
    ).json()["patient"]["id"]
    other = register("Rep B")
    mid = join(rep, pid, other, "family", ["view_profile"])
    assert (
        rep.patch(f"/api/patients/{pid}/members/{mid}", {"is_representative": True}).status_code
        == 200
    )  # no elder yet: allowed
    demote = other.patch(f"/api/patients/{pid}/members/{mid}", {"permissions": ["view_profile"]})
    assert demote.status_code == 403  # B cannot change own access either (separate rule)
    rep_members = rep.get(f"/api/patients/{pid}/members").json()
    rep_mid = next(m["id"] for m in rep_members if m["user_id"] == rep.user["id"])
    strip = other.patch(f"/api/patients/{pid}/members/{rep_mid}", {"permissions": ["view_profile"]})
    assert strip.status_code == 403
    assert (
        "manage_care_team"
        in next(m for m in rep.get(f"/api/patients/{pid}/members").json() if m["id"] == rep_mid)[
            "permissions"
        ]
    )


def test_change_password_is_throttled():
    api = register("Thr Ottle")
    for _ in range(5):
        api.post(
            "/api/auth/change-password",
            {"current_password": "wrong guess", "new_password": "new pass phrase 1"},
        )
    res = api.post(
        "/api/auth/change-password",
        {"current_password": "correct horse battery", "new_password": "new pass phrase 1"},
    )
    assert res.status_code == 429
