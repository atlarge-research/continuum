"""Landscape report layout with space reserved for explanations and legends."""
import matplotlib.pyplot as plt

BLUE = "#2864b4"
ORANGE = "#c56a16"
GREEN = "#39753b"
COLORS = (BLUE, ORANGE, GREEN)
SUPPLEMENT_SCHEMA = "opendc-report-supplement-v1"


def page(title, takeaway, rows=2, columns=2):
    """Create a landscape slide with reserved heading, legend and footer space.

    Args:
        title (str): Scenario or question answered by this page.
        takeaway (str): One sentence interpreting its evidence.
        rows (int): Number of panel rows.
        columns (int): Number of panel columns.

    Returns:
        tuple: Figure and a two-dimensional array of axes.
    """
    figure, axes = plt.subplots(rows, columns, figsize=(11.69, 8.27), squeeze=False)
    figure.subplots_adjust(left=0.08, right=0.97, top=0.80, bottom=0.20, hspace=0.85, wspace=0.32)
    figure.suptitle(title, fontsize=17, y=0.965)
    figure.text(0.08, 0.905, takeaway, fontsize=10)
    for axis in axes.flat:
        axis.tick_params(labelbottom=True, labelleft=True, labelsize=9)
        axis.grid(alpha=0.18)
    return figure, axes


def finish(pdf, figure, note):
    """Save a slide with explanatory text outside the plotted data.

    Args:
        pdf (PdfPages): Open report writer.
        figure (Figure): Completed landscape page.
        note (str): Short scope/coverage explanation, with explicit line breaks.
    """
    figure.text(0.08, 0.045, note, fontsize=9, linespacing=1.5)
    pdf.savefig(figure)
    plt.close(figure)


def panel(axis, title, xlabel, ylabel):
    """Apply readable conclusions and axis labels consistently.

    Args:
        axis (Axes): Panel to label.
        title (str): Short finding, optionally followed by an identifying line.
        xlabel (str): Horizontal variable and units.
        ylabel (str): Vertical variable and units.
    """
    axis.set_title(title, fontsize=10, pad=10)
    axis.set_xlabel(xlabel, fontsize=9)
    axis.set_ylabel(ylabel, fontsize=9)
