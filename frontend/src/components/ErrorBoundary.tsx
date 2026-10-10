import { Component, type ReactNode } from "react";

/** One broken panel must not take down the dashboard. */
export class PanelBoundary extends Component<{ name: string; children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidUpdate(prev: { children: ReactNode }) {
    if (prev.children !== this.props.children && this.state.error) this.setState({ error: null });
  }
  render() {
    if (this.state.error) {
      return (
        <section className="card p-4 text-sm">
          <h2 className="font-semibold">{this.props.name} could not be displayed</h2>
          <p className="text-ink2">{this.state.error.message}. The rest of the dashboard is unaffected.</p>
        </section>
      );
    }
    return this.props.children;
  }
}
