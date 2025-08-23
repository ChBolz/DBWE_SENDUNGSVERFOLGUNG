from flask import Flask

def create_app():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Hello, World! This is the Shipment App (minimal)."

    return app

# for local `python app.py` run
if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)