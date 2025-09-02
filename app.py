from flask import Flask, render_template, request, url_for

def create_app():
    app = Flask(__name__)
    # Not used yet, but handy later for sessions/flash
    app.config["SECRET_KEY"] = "dev"

    @app.route("/")
    def index():
        return render_template("index.html")

    # --- Login (placeholder) ---
    @app.route("/login", methods=["GET"])
    def login():
        return render_template("login.html")

    @app.route("/login", methods=["POST"])
    def login_post():
        # We'll implement real auth later
        username = request.form.get("username", "")
        return f"Login not implemented yet. You posted username='{username}'.", 501

    # --- Register (placeholder) ---
    @app.route("/register", methods=["GET"])
    def register():
        return render_template("register.html")

    @app.route("/register", methods=["POST"])
    def register_post():
        # We'll implement real registration later
        username = request.form.get("username", "")
        email = request.form.get("email", "")
        return f"Register not implemented yet. You posted username='{username}', email='{email}'.", 501

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
