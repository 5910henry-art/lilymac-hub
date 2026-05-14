# admin.py
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from betting.models import db, User, Match

def register_admin_routes(app):

    # -------------------------
    # Update match route
    # -------------------------
    @app.route("/admin/update-match", methods=["POST"])
    @jwt_required()
    def update_match():
        uid = int(get_jwt_identity())
        user = db.session.get(User, uid)
        if not user or not user.is_admin:
            return jsonify({"error": "forbidden"}), 403

        data = request.json or {}
        match = db.session.get(Match, data.get("match_id"))
        if not match:
            return jsonify({"error": "not found"}), 404

        home = data.get("home", match.home_score)
        away = data.get("away", match.away_score)

        # validation
        try:
            if int(home) < 0 or int(away) < 0:
                return jsonify({"error": "invalid score"}), 400
        except Exception:
            return jsonify({"error": "invalid score"}), 400

        match.home_score = home
        match.away_score = away
        match.status = data.get("status", match.status)

        db.session.commit()
        return jsonify({"msg": "updated"})


    # -------------------------
    # Create match route
    # -------------------------
    @app.route("/admin/create-match", methods=["POST"])
    @jwt_required()
    def create_match():
        uid = int(get_jwt_identity())
        user = db.session.get(User, uid)
        if not user or not user.is_admin:
            return jsonify({"error": "forbidden"}), 403

        data = request.json or {}
        team_a = data.get("team_a")
        team_b = data.get("team_b")
        if not team_a or not team_b:
            return jsonify({"error": "team_a and team_b required"}), 400

        # Use proper field names from your model
        match = Match(home_team=team_a, away_team=team_b)
        db.session.add(match)
        db.session.commit()

        return jsonify({
            "msg": "match created",
            "match_id": match.id
        }), 201
